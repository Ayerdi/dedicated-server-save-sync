import hashlib
import io
import json
import os
import signal
import sqlite3
import subprocess
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event, get_ident

import pytest

from save_sync.app import create_app, digest, iso, utcnow

WORLD_GUID = "A7E97BAA767DB9029EF013BB71E993A0"


class _ThreadThatFailsToStart(threading.Thread):
    """Simula que el SO no puede crear más threads (p. ej. límite de
    recursos). start() lanza excepción, reproduciendo el escenario en el que
    el supervisor de backup no puede iniciarse tras la publicación confirmada."""

    def start(self):
        raise RuntimeError("no se pueden crear más threads")


def zip_payload(marker=b"save"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Pal/Saved/SaveGames/world.sav", marker)
    return stream.getvalue()


@pytest.fixture()
def app(tmp_path):
    storage = tmp_path / "storage"
    application = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_STORAGE_PATH": str(storage),
            "SAVE_SYNC_DB_PATH": str(storage / "palworld.sqlite3"),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
            "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
            "SAVE_SYNC_LOCK_TTL_SECONDS": 300,
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
            "SAVE_SYNC_WEB_USERS": (
                "admin:admin,player:player,playerAlias1:player,playerAlias2:player"
            ),
            "SAVE_SYNC_USER_IDENTITIES_JSON": (
                '{"admin":{"displayName":"Host A","slot":"host-a"},'
                '"player":{"displayName":"Host B","slot":"host-b"},'
                '"playerAlias1":{"displayName":"Host B","slot":"host-b"},'
                '"playerAlias2":{"displayName":"Host B","slot":"host-b"}}'
            ),
        }
    )
    with application.extensions["save_sync_connect"]() as db:
        users = db.execute("SELECT id,username FROM users").fetchall()
        for user in users:
            token = f"token-{user['username']}"
            db.execute(
                "INSERT INTO api_tokens(user_id,name,token_hash,created_at) VALUES(?,?,?,?)",
                (user["id"], "test", digest(token), iso(utcnow())),
            )
    return application


def headers(username="admin"):
    return {"Authorization": f"Bearer token-{username}"}


def lock(client, username="admin", client_id="pc"):
    return client.post(
        "/api/games/palworld/lock",
        headers=headers(username),
        json={
            "owner": "Host A" if username.lower() == "admin" else "Host B",
            "clientId": client_id,
        },
    )


def upload(
    client,
    session_id,
    base_version,
    payload,
    username="admin",
    save_identity=WORLD_GUID,
):
    return client.post(
        "/api/games/palworld/upload",
        headers=headers(username),
        data={
            "file": (io.BytesIO(payload), "save.zip"),
            "sessionId": session_id,
            "baseVersion": str(base_version),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "worldGuid": save_identity,
        },
        content_type="multipart/form-data",
    )


def publish(app, marker=b"save", username="admin"):
    with app.test_client() as client:
        acquired = lock(client, username, f"pc-{marker.decode()}")
        assert acquired.status_code == 201
        body = acquired.get_json()
        result = upload(
            client,
            body["sessionId"],
            body["baseVersion"],
            zip_payload(marker),
            username,
        )
        assert result.status_code == 201
        return result.get_json()


def test_two_simultaneous_locks_have_one_winner(app):
    def acquire(username):
        with app.test_client() as client:
            response = lock(client, username, f"pc-{username}")
            return response.status_code, response.get_json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acquire, ["admin", "player"]))

    assert sorted(status for status, _ in results) == [201, 409]
    loser = next(body for status, body in results if status == 409)
    assert loser["error"] == "lock_occupied"


def test_two_simultaneous_uploads_same_session_publish_once(app):
    with app.test_client() as client:
        acquired = lock(client).get_json()
    payloads = [zip_payload(b"a"), zip_payload(b"b")]

    def send(payload):
        with app.test_client() as client:
            response = upload(client, acquired["sessionId"], 0, payload)
            return response.status_code, response.get_json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, payloads))

    assert sorted(status for status, _ in results) == [201, 409]
    assert (
        next(body for status, body in results if status == 409)["error"]
        == "version_conflict"
    )
    with app.extensions["save_sync_connect"]() as db:
        assert db.execute("SELECT count(*) FROM versions").fetchone()[0] == 1
        assert db.execute("SELECT version FROM current_save").fetchone()[0] == 1


def test_expired_lock_cannot_heartbeat_and_can_be_reacquired(app):
    with app.test_client() as client:
        session = lock(client).get_json()["sessionId"]
        with app.extensions["save_sync_connect"]() as db:
            db.execute(
                "UPDATE active_lock SET expires_at=?",
                (iso(utcnow() - timedelta(seconds=1)),),
            )
        expired = client.post(
            "/api/games/palworld/heartbeat", headers=headers(), json={"sessionId": session}
        )
        assert expired.status_code == 409
        assert expired.get_json()["error"] == "lock_expired"
        assert lock(client, "player", "pc-new").status_code == 201


def test_restore_is_rejected_while_lock_active(app):
    publish(app, b"v1")
    with app.test_client() as client:
        assert lock(client, "player", "pc-player").status_code == 201
        response = client.post(
            "/api/games/palworld/history/1/restore", headers=headers("admin")
        )
    assert response.status_code == 409
    assert response.get_json()["error"] == "lock_occupied"


def test_multiple_admin_publications_keep_one_canonical_version(app):
    for number in range(1, 7):
        publish(app, f"v{number}".encode(), "admin")

    with app.extensions["save_sync_connect"]() as db:
        versions = [
            row[0]
            for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
        current = db.execute("SELECT version FROM current_save").fetchone()[0]
    assert current == 6
    assert versions == [6]
    backups = Path(app.config["SAVE_SYNC_STORAGE_PATH"], "backups")
    assert len(list(backups.glob("save-v*.zip"))) == 1


def test_multiple_player_aliases_share_one_canonical_slot(app):
    publish(app, b"alias-one", "playerAlias1")
    publish(app, b"playertf", "playerAlias2")
    publish(app, b"player", "player")
    with app.extensions["save_sync_connect"]() as db:
        rows = db.execute(
            "SELECT v.version,u.username FROM versions v "
            "JOIN users u ON u.id=v.updated_by ORDER BY v.version"
        ).fetchall()
    assert [(row["version"], row["username"]) for row in rows] == [(3, "player")]


def test_alternating_players_keep_exactly_two_canonical_versions(app):
    publish(app, b"admin-1", "admin")
    publish(app, b"player-1", "player")
    publish(app, b"admin-2", "admin")
    publish(app, b"player-2", "playerAlias1")
    with app.extensions["save_sync_connect"]() as db:
        versions = [
            row[0]
            for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
    assert versions == [3, 4]
    backups = Path(app.config["SAVE_SYNC_STORAGE_PATH"], "backups")
    assert len(list(backups.glob("save-v*.zip"))) == 2


def test_restore_replaces_restoring_admin_canonical_slot(app):
    publish(app, b"player", "player")
    publish(app, b"admin", "admin")
    with app.test_client() as client:
        restored = client.post(
            "/api/games/palworld/history/1/restore", headers=headers("admin")
        )
    assert restored.status_code == 201
    with app.extensions["save_sync_connect"]() as db:
        rows = db.execute(
            "SELECT v.version,u.username FROM versions v "
            "JOIN users u ON u.id=v.updated_by ORDER BY v.version"
        ).fetchall()
    assert [(row["version"], row["username"]) for row in rows] == [
        (1, "player"),
        (3, "admin"),
    ]
    backups = Path(app.config["SAVE_SYNC_STORAGE_PATH"], "backups")
    assert len(list(backups.glob("save-v*.zip"))) == 2


def test_restart_reconciles_orphans_and_filesystem_has_at_most_two_zips(app):
    publish(app, b"admin", "admin")
    publish(app, b"player", "player")
    backups = Path(app.config["SAVE_SYNC_STORAGE_PATH"], "backups")
    (backups / "save-v999999.zip").write_bytes(zip_payload(b"orphan"))
    assert len(list(backups.glob("save-v*.zip"))) == 3
    create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_STORAGE_PATH": app.config["SAVE_SYNC_STORAGE_PATH"],
            "SAVE_SYNC_DB_PATH": app.config["SAVE_SYNC_DB_PATH"],
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
        }
    )
    assert len(list(backups.glob("save-v*.zip"))) == 2


def test_cleanup_snapshot_cannot_delete_a_concurrent_new_publication(app, monkeypatch):
    publish(app, b"admin-old", "admin")
    cleanup_entered = Event()
    release_cleanup = Event()
    publisher_thread = {}
    original_glob = Path.glob

    def paused_glob(path, pattern):
        if (
            pattern == "save-v*.zip"
            and get_ident() == publisher_thread.get("identity")
            and not cleanup_entered.is_set()
        ):
            cleanup_entered.set()
            assert release_cleanup.wait(timeout=5)
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", paused_glob)

    def publish_player_with_paused_cleanup():
        publisher_thread["identity"] = get_ident()
        return publish(app, b"player", "player")

    with ThreadPoolExecutor(max_workers=2) as pool:
        old_cleanup = pool.submit(publish_player_with_paused_cleanup)
        assert cleanup_entered.wait(timeout=5)
        newer_publish = pool.submit(publish, app, b"admin-new", "admin")
        assert not newer_publish.done()
        release_cleanup.set()
        assert old_cleanup.result(timeout=10)["version"] == 2
        assert newer_publish.result(timeout=10)["version"] == 3

    backups = Path(app.config["SAVE_SYNC_STORAGE_PATH"], "backups")
    with app.extensions["save_sync_connect"]() as db:
        current = db.execute(
            "SELECT v.version,v.path FROM current_save c "
            "JOIN versions v ON v.version=c.version"
        ).fetchone()
    assert current["version"] == 3
    assert Path(app.config["SAVE_SYNC_STORAGE_PATH"], current["path"]).is_file()
    assert sorted(path.name for path in backups.glob("save-v*.zip")) == [
        "save-v000002.zip",
        "save-v000003.zip",
    ]


def test_protection_operation_and_button_are_removed(app):
    publish(app, b"v1")
    with app.test_client() as client:
        endpoint = client.post(
            "/api/games/palworld/history/1/protect",
            headers=headers("admin"),
            json={"protected": True},
        )
        panel = client.get(
            "/games/palworld",
            headers={
                "X-authentik-username": "admin",
                "X-Palworld-Proxy-Secret": "proxy-test-secret",
            },
        )
    assert endpoint.status_code == 404
    assert "/protect" not in panel.get_data(as_text=True)
    assert "Proteger" not in panel.get_data(as_text=True)


def test_retention_per_slot_keeps_configured_number_of_versions(tmp_path):
    storage = tmp_path / "storage3"
    application = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_STORAGE_PATH": str(storage),
            "SAVE_SYNC_DB_PATH": str(storage / "palworld.sqlite3"),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
            "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
            "SAVE_SYNC_LOCK_TTL_SECONDS": 300,
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
            "SAVE_SYNC_RETENTION_PER_SLOT": 3,
            "SAVE_SYNC_WEB_USERS": "admin:admin,player:player",
            "SAVE_SYNC_USER_IDENTITIES_JSON": (
                '{"admin":{"displayName":"Host A","slot":"host-a"},'
                '"player":{"displayName":"Host B","slot":"host-b"}}'
            ),
        }
    )
    with application.extensions["save_sync_connect"]() as db:
        users = db.execute("SELECT id,username FROM users").fetchall()
        for user in users:
            token = f"token-{user['username']}"
            db.execute(
                "INSERT INTO api_tokens(user_id,name,token_hash,created_at) VALUES(?,?,?,?)",
                (user["id"], "test", digest(token), iso(utcnow())),
            )
    for number in range(1, 7):
        publish(application, f"a{number}".encode(), "admin")
        publish(application, f"p{number}".encode(), "player")
    with application.extensions["save_sync_connect"]() as db:
        versions = [
            row[0]
            for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
    assert versions == [7, 8, 9, 10, 11, 12]
    backups = storage / "backups"
    assert len(list(backups.glob("save-v*.zip"))) == 6


def test_post_publish_hook_runs_and_never_blocks_publication(app, monkeypatch):
    hook_calls = []

    class FakeProcess:
        def wait(self, timeout=None):
            return 0

    def record_hook(command, **kwargs):
        hook_calls.append((command, kwargs.get("env", {})))
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", record_hook)
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"
    result = publish(app, b"hook-check")
    assert result["version"] == 1
    assert len(hook_calls) == 1
    assert hook_calls[0][0] == ["restic", "backup", "/data/save-sync"]
    env = hook_calls[0][1]
    assert env["SAVE_SYNC_PUBLISHED_VERSION"] == "1"
    assert env["SAVE_SYNC_PUBLISHED_IDENTITY"] == WORLD_GUID

    def failing_hook(command, **kwargs):
        raise OSError("injected hook failure")

    monkeypatch.setattr(subprocess, "Popen", failing_hook)
    result = publish(app, b"hook-fail")
    assert result["version"] == 2
    with app.test_client() as client:
        downloaded = client.get("/api/games/palworld/download", headers=headers())
    assert downloaded.status_code == 200


def test_post_publish_hook_with_malformed_quotes_still_returns_201(app):
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = 'restic backup "mal cerrado'
    result = publish(app, b"malformed")
    assert result["version"] == 1
    with app.test_client() as client:
        downloaded = client.get("/api/games/palworld/download", headers=headers())
    assert downloaded.status_code == 200


def test_backup_pending_version_survives_cleanup(app, monkeypatch):
    blocker = Event()

    class HangingProcess:
        def wait(self, timeout=None):
            blocker.wait(timeout=30)
            return 0

    def slow_hook(command, **kwargs):
        return HangingProcess()

    monkeypatch.setattr(subprocess, "Popen", slow_hook)
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"
    app.config["SAVE_SYNC_RETENTION_PER_SLOT"] = 1

    publish(app, b"v1", "admin")
    publish(app, b"v2", "admin")
    with app.extensions["save_sync_connect"]() as db:
        pending = {
            row[0] for row in db.execute("SELECT version FROM pending_backups")
        }
        versions = [
            row[0] for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
    assert 1 in pending
    assert versions == [1, 2]
    backups = Path(app.config["SAVE_SYNC_STORAGE_PATH"], "backups")
    assert len(list(backups.glob("save-v*.zip"))) == 2
    blocker.set()


def test_backup_hook_result_is_audited(app, monkeypatch):
    class FailingProcess:
        def wait(self, timeout=None):
            return 1

    def failing_hook(command, **kwargs):
        return FailingProcess()

    monkeypatch.setattr(subprocess, "Popen", failing_hook)
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"
    publish(app, b"audit-check")
    row = None
    for _ in range(100):
        with app.extensions["save_sync_connect"]() as db:
            row = db.execute(
                "SELECT event,success,details FROM audit WHERE event=? ORDER BY id DESC",
                ("backup_hook_failed",),
            ).fetchone()
        if row:
            break
        Event().wait(0.05)
    assert row is not None
    assert row["success"] == 0
    details = json.loads(row["details"])
    assert details["version"] == 1
    assert details["exitCode"] == 1


def test_backup_hook_timeout_terminates_and_audits_failure(app, monkeypatch):
    sent_signals = []

    def fake_killpg(pgid, sig):
        sent_signals.append(sig)

    monkeypatch.setattr(os, "killpg", fake_killpg)

    class HangingProcess:
        def __init__(self):
            self.pid = os.getpid()
            self.calls = 0

        def wait(self, timeout=None):
            self.calls += 1
            # El proceso ignora tanto SIGTERM como SIGKILL (p. ej. un nieto
            # zombie) para ejercer las ramas de timeout de terminate_process_group.
            if self.calls <= 3:
                raise subprocess.TimeoutExpired(
                    cmd=["restic"], timeout=timeout or 0
                )
            return 0

    captured = {}

    def hanging_hook(command, **kwargs):
        captured["process"] = HangingProcess()
        return captured["process"]

    monkeypatch.setattr(subprocess, "Popen", hanging_hook)
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"
    publish(app, b"timeout")
    process = captured["process"]
    row = None
    for _ in range(100):
        with app.extensions["save_sync_connect"]() as db:
            row = db.execute(
                "SELECT success,details FROM audit WHERE event=? ORDER BY id DESC",
                ("backup_hook_failed",),
            ).fetchone()
        if row:
            break
        Event().wait(0.05)
    assert row is not None
    assert row["success"] == 0
    details = json.loads(row["details"])
    assert details["version"] == 1
    assert details["timedOut"] == 1
    assert signal.SIGTERM in sent_signals
    assert signal.SIGKILL in sent_signals
    assert process.calls >= 3


def test_stale_pending_backup_is_preserved_until_supervisor_resolves_it(app):
    from save_sync.backup_supervisor import BackupSupervisor

    app.config["SAVE_SYNC_RETENTION_PER_SLOT"] = 1
    publish(app, b"v1", "admin")
    publish(app, b"v2", "admin")
    with app.extensions["save_sync_connect"]() as db:
        old_started = iso(utcnow() - timedelta(seconds=9999))
        db.execute(
            "INSERT OR REPLACE INTO pending_backups(version,started_at) VALUES(?,?)",
            (2, old_started),
        )
    publish(app, b"v3", "admin")

    storage = Path(app.config["SAVE_SYNC_STORAGE_PATH"])
    with app.extensions["save_sync_connect"]() as db:
        pending = {
            row[0] for row in db.execute("SELECT version FROM pending_backups")
        }
        versions = [
            row[0] for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
    assert pending == {2}
    assert versions == [2, 3]
    assert (storage / "backups/save-v000002.zip").is_file()

    class SuccessfulProcess:
        pid = 999999

        def wait(self, timeout=None):
            return 0

    supervisor = BackupSupervisor(
        storage_path=storage,
        db_path=app.config["SAVE_SYNC_DB_PATH"],
        command="true",
        timeout_seconds=30,
        poll_seconds=0.01,
        retention_per_slot=1,
        popen=lambda *args, **kwargs: SuccessfulProcess(),
    )
    assert supervisor.run_once() is True

    with app.extensions["save_sync_connect"]() as db:
        pending = {
            row[0] for row in db.execute("SELECT version FROM pending_backups")
        }
        versions = [
            row[0] for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
    assert pending == set()
    assert versions == [3]
    assert not (storage / "backups/save-v000002.zip").exists()
    assert (storage / "backups/save-v000003.zip").is_file()


def test_post_publish_hook_popen_failure_clears_pending_backups(app, monkeypatch):
    def raise_popen(*args, **kwargs):
        raise OSError("simulated restic not found")

    monkeypatch.setattr(subprocess, "Popen", raise_popen)
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"
    app.config["SAVE_SYNC_RETENTION_PER_SLOT"] = 1
    result = publish(app, b"no-restic")
    assert result["version"] == 1
    with app.extensions["save_sync_connect"]() as db:
        pending = [
            row[0] for row in db.execute("SELECT version FROM pending_backups")
        ]
        versions = [
            row[0] for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
    assert pending == []
    assert versions == [1]


def test_cleanup_runs_after_backup_completes(app, monkeypatch):
    completed = Event()

    class SlowProcess:
        def wait(self, timeout=None):
            completed.wait(timeout=30)
            return 0

    def slow_hook(command, **kwargs):
        return SlowProcess()

    monkeypatch.setattr(subprocess, "Popen", slow_hook)
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"
    app.config["SAVE_SYNC_RETENTION_PER_SLOT"] = 1
    publish(app, b"v1", "admin")
    publish(app, b"v2", "admin")
    with app.extensions["save_sync_connect"]() as db:
        versions = [
            row[0] for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
    assert versions == [1, 2]
    completed.set()
    for _ in range(100):
        with app.extensions["save_sync_connect"]() as db:
            pending = [
                row[0] for row in db.execute("SELECT version FROM pending_backups")
            ]
            versions = [
                row[0] for row in db.execute("SELECT version FROM versions ORDER BY version")
            ]
        if pending == [] and versions == [2]:
            break
        Event().wait(0.05)
    assert pending == []
    assert versions == [2]


def test_canonical_cleanup_failure_does_not_invalidate_published_save(app, monkeypatch):
    publish(app, b"v1")
    publish(app, b"v2")
    publish(app, b"v3")
    original_unlink = Path.unlink

    def fail_old_backup_once(path, *args, **kwargs):
        if path.name == "save-v000003.zip":
            raise OSError("injected canonical cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_old_backup_once)
    result = publish(app, b"v4")
    assert result["version"] == 4
    with app.test_client() as client:
        downloaded = client.get("/api/games/palworld/download", headers=headers())
    assert downloaded.status_code == 200
    assert downloaded.headers["X-Palworld-Version"] == "4"


def test_database_failure_after_move_preserves_current_but_retry_must_work(app):
    publish(app, b"v1")
    with app.test_client() as client:
        acquired = lock(client).get_json()
        with app.extensions["save_sync_connect"]() as db:
            db.execute(
                "CREATE TRIGGER fail_v2 BEFORE INSERT ON versions "
                "WHEN NEW.version=2 BEGIN SELECT RAISE(ABORT,'injected failure'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            upload(client, acquired["sessionId"], 1, zip_payload(b"v2"))

        with app.extensions["save_sync_connect"]() as db:
            assert db.execute("SELECT version FROM current_save").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM versions").fetchone()[0] == 1
            db.execute("DROP TRIGGER fail_v2")

        # Tras recrear la app (equivalente a reiniciar el proceso), el mismo lock
        # sigue vigente y un posible fichero huérfano no debe bloquear el reintento.
        restarted = create_app(
            {
                "TESTING": True,
                "SAVE_SYNC_STORAGE_PATH": app.config["SAVE_SYNC_STORAGE_PATH"],
                "SAVE_SYNC_DB_PATH": app.config["SAVE_SYNC_DB_PATH"],
                "SAVE_SYNC_REQUIRE_HTTPS": False,
                "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
            }
        )
        retried = upload(
            restarted.test_client(), acquired["sessionId"], 1, zip_payload(b"v2")
        )
        assert retried.status_code == 201
        assert retried.get_json()["version"] == 2


def test_restore_failure_after_move_is_compensated_and_retryable(app):
    publish(app, b"v1")
    with app.extensions["save_sync_connect"]() as db:
        db.execute(
            "CREATE TRIGGER fail_restore BEFORE INSERT ON versions "
            "WHEN NEW.restored_from_version IS NOT NULL "
            "BEGIN SELECT RAISE(ABORT,'injected restore failure'); END"
        )
    with app.test_client() as client, pytest.raises(sqlite3.IntegrityError):
        client.post("/api/games/palworld/history/1/restore", headers=headers("admin"))

    storage = app.config["SAVE_SYNC_STORAGE_PATH"]
    assert not Path(storage, "backups/save-v000002.zip").exists()
    with app.extensions["save_sync_connect"]() as db:
        assert db.execute("SELECT version FROM current_save").fetchone()[0] == 1
        db.execute("DROP TRIGGER fail_restore")
    with app.test_client() as client:
        retried = client.post(
            "/api/games/palworld/history/1/restore", headers=headers("admin")
        )
    assert retried.status_code == 201
    assert retried.get_json()["version"] == 2


def test_restart_uses_persisted_lock_and_current_version(app):
    publish(app, b"v1")
    with app.test_client() as client:
        acquired = lock(client, "player", "pc-player").get_json()

    restarted = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_STORAGE_PATH": app.config["SAVE_SYNC_STORAGE_PATH"],
            "SAVE_SYNC_DB_PATH": app.config["SAVE_SYNC_DB_PATH"],
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
        }
    )
    with restarted.test_client() as client:
        status = client.get("/api/games/palworld/status", headers=headers("admin"))
        heartbeat = client.post(
            "/api/games/palworld/heartbeat",
            headers=headers("player"),
            json={"sessionId": acquired["sessionId"]},
        )
    assert status.get_json()["version"] == 1
    assert status.get_json()["locked"] is True
    assert heartbeat.status_code == 200


def test_post_publish_hook_thread_start_failure_never_breaks_publication(
    app, monkeypatch
):
    """Thread.start() falla tras publicación confirmada: sigue 201 y se libera
    el marcador de backup."""
    monkeypatch.setattr(threading, "Thread", _ThreadThatFailsToStart)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: None)

    class DummyProcess:
        pid = os.getpid()

        def wait(self, timeout=None):
            return -15

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: DummyProcess())
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"
    app.config["SAVE_SYNC_RETENTION_PER_SLOT"] = 1

    result = publish(app, b"v1")
    assert result["version"] == 1
    with app.test_client() as client:
        downloaded = client.get("/api/games/palworld/download", headers=headers("admin"))
    assert downloaded.status_code == 200
    with app.extensions["save_sync_connect"]() as db:
        pending = [row[0] for row in db.execute("SELECT version FROM pending_backups")]
        versions = [
            row[0]
            for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
        failed = db.execute(
            "SELECT details FROM audit WHERE event=?", ("backup_hook_failed",)
        ).fetchall()
    assert pending == []
    assert versions == [1]
    assert any(
        json.loads(row["details"]).get("reason") == "thread_start_failed"
        for row in failed
    )


def test_history_delete_rejects_version_with_pending_backup(tmp_path, monkeypatch):
    """ 🔴 #2: borrar una versión con backup en curso devuelve 409; vuelve a
    funcionar (200) una vez el backup termina y se libera el marcador.

    Usa una app con retención=2 (más alto que la versión publicada) para que el
    cleanup post-backup no elimine previamente v1, dejando constar el
    comportamiento del endpoint admin frente a pending_backups."""
    blocker = Event()
    storage = tmp_path / "storage"

    class HangingProcess:
        pid = os.getpid()

        def wait(self, timeout=None):
            blocker.wait(timeout=30)
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: HangingProcess())
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: None)

    application = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_STORAGE_PATH": str(storage),
            "SAVE_SYNC_DB_PATH": str(storage / "palworld.sqlite3"),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
            "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
            "SAVE_SYNC_LOCK_TTL_SECONDS": 300,
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
            "SAVE_SYNC_RETENTION_PER_SLOT": 2,
            "SAVE_SYNC_POST_PUBLISH_COMMAND": "restic backup /data/save-sync",
            "SAVE_SYNC_WEB_USERS": "admin:admin,player:player",
            "SAVE_SYNC_USER_IDENTITIES_JSON": (
                '{"admin":{"displayName":"Host A","slot":"host-a"},'
                '"player":{"displayName":"Host B","slot":"host-b"}}'
            ),
        }
    )
    with application.extensions["save_sync_connect"]() as db:
        admin = db.execute("SELECT id FROM users WHERE username=?", ("admin",)).fetchone()
        db.execute(
            "INSERT INTO api_tokens(user_id,name,token_hash,created_at) VALUES(?,?,?,?)",
            (admin["id"], "test", digest("token-admin"), iso(utcnow())),
        )

    publish(application, b"v1")
    publish(application, b"v2")

    with application.test_client() as client:
        blocked = client.delete(
            "/api/games/palworld/history/1", headers=headers("admin"))
    assert blocked.status_code == 409
    assert blocked.get_json()["error"] == "backup_in_progress"

    blocker.set()
    for _ in range(100):
        with application.extensions["save_sync_connect"]() as db:
            gone = db.execute("SELECT 1 FROM pending_backups WHERE version=1").fetchone()
        if gone is None:
            break
        Event().wait(0.05)

    with application.test_client() as client:
        deleted = client.delete(
            "/api/games/palworld/history/1", headers=headers("admin"))
    assert deleted.status_code == 200