import json
import sqlite3
import subprocess

from save_sync import create_app
from save_sync.backup_supervisor import BackupSupervisor

WORLD_GUID = "A7E97BAA767DB9029EF013BB71E993A0"


def bootstrap_storage(tmp_path, retention=1):
    storage = tmp_path / "storage"
    db_path = storage / "save-sync.sqlite3"
    app = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_STORAGE_PATH": str(storage),
            "SAVE_SYNC_DB_PATH": str(db_path),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
            "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
            "SAVE_SYNC_RETENTION_PER_SLOT": retention,
        }
    )
    return app, storage, db_path


def queue_version(
    app,
    storage,
    version,
    *,
    username="admin",
    queued_at="2026-01-01T00:00:00Z",
):
    relative = f"backups/save-v{version:06d}.zip"
    payload = f"version-{version}".encode()
    (storage / relative).write_bytes(payload)
    with app.extensions["save_sync_connect"]() as db:
        user_id = db.execute(
            "SELECT id FROM users WHERE username=?", (username,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO versions(version,path,sha256,size,updated_by,updated_at,base_version,save_identity) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                version,
                relative,
                "0" * 64,
                len(payload),
                user_id,
                queued_at,
                max(0, version - 1),
                WORLD_GUID,
            ),
        )
        db.execute(
            "INSERT INTO current_save(singleton,version) VALUES(1,?) "
            "ON CONFLICT(singleton) DO UPDATE SET version=excluded.version",
            (version,),
        )
        db.execute(
            "INSERT INTO pending_backups(version,started_at) VALUES(?,?)",
            (version, queued_at),
        )
    return relative


class SuccessfulProcess:
    pid = 999999

    def wait(self, timeout=None):
        return 0


class FailingProcess:
    pid = 999999

    def wait(self, timeout=None):
        return 7


def make_supervisor(storage, db_path, popen, *, retention=1):
    return BackupSupervisor(
        storage_path=storage,
        db_path=db_path,
        command="restic backup /data/save-sync",
        timeout_seconds=30,
        poll_seconds=0.01,
        retention_per_slot=retention,
        identities={
            "admin": {"displayName": "Host A", "slot": "host-a"},
            "player": {"displayName": "Host B", "slot": "host-b"},
        },
        popen=popen,
    )


def test_supervisor_processes_durable_job_and_audits_success(tmp_path):
    app, storage, db_path = bootstrap_storage(tmp_path)
    relative = queue_version(app, storage, 1)
    calls = []

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return SuccessfulProcess()

    supervisor = make_supervisor(storage, db_path, popen)
    assert supervisor.run_once() is True

    assert calls[0][0] == ["restic", "backup", "/data/save-sync"]
    env = calls[0][1]["env"]
    assert env["SAVE_SYNC_PUBLISHED_VERSION"] == "1"
    assert env["SAVE_SYNC_PUBLISHED_PATH"] == str(storage / relative)
    assert env["SAVE_SYNC_PUBLISHED_IDENTITY"] == WORLD_GUID

    with app.extensions["save_sync_connect"]() as db:
        assert db.execute("SELECT count(*) FROM pending_backups").fetchone()[0] == 0
        rows = db.execute(
            "SELECT event,success,details FROM audit "
            "WHERE event LIKE 'backup_hook_%' ORDER BY id"
        ).fetchall()
    assert [row["event"] for row in rows] == [
        "backup_hook_started",
        "backup_hook_completed",
    ]
    assert rows[-1]["success"] == 1
    assert json.loads(rows[-1]["details"])["version"] == 1


def test_supervisor_audits_nonzero_exit_and_releases_job(tmp_path):
    app, storage, db_path = bootstrap_storage(tmp_path)
    queue_version(app, storage, 1)
    supervisor = make_supervisor(storage, db_path, lambda *a, **k: FailingProcess())

    assert supervisor.run_once() is True

    with app.extensions["save_sync_connect"]() as db:
        assert db.execute("SELECT count(*) FROM pending_backups").fetchone()[0] == 0
        failed = db.execute(
            "SELECT success,details FROM audit WHERE event='backup_hook_failed'"
        ).fetchone()
    assert failed["success"] == 0
    assert json.loads(failed["details"])["exitCode"] == 7


def test_launch_failure_is_audited_without_losing_publication(tmp_path):
    app, storage, db_path = bootstrap_storage(tmp_path)
    relative = queue_version(app, storage, 1)

    def broken_popen(*_args, **_kwargs):
        raise OSError("restic no disponible")

    supervisor = make_supervisor(storage, db_path, broken_popen)
    assert supervisor.run_once() is True

    assert (storage / relative).is_file()
    with app.extensions["save_sync_connect"]() as db:
        assert db.execute("SELECT count(*) FROM pending_backups").fetchone()[0] == 0
        failed = db.execute(
            "SELECT details FROM audit WHERE event='backup_hook_failed'"
        ).fetchone()
    details = json.loads(failed["details"])
    assert details["reason"] == "hook_launch_failed"
    assert details["version"] == 1


def test_supervisor_restart_reclaims_pending_job_and_applies_retention(tmp_path):
    app, storage, db_path = bootstrap_storage(tmp_path, retention=1)
    old_relative = queue_version(app, storage, 1, queued_at="2025-01-01T00:00:00Z")

    # Simula una publicación posterior mientras v1 sigue protegida por la cola.
    new_relative = queue_version(app, storage, 2, queued_at="2026-01-01T00:00:00Z")
    with app.extensions["save_sync_connect"]() as db:
        # v2 no necesita protección para este test; queremos comprobar que al
        # resolver v1 la retención vuelve al único canónico del slot.
        db.execute("DELETE FROM pending_backups WHERE version=2")

    restarted = make_supervisor(storage, db_path, lambda *a, **k: SuccessfulProcess())
    assert restarted.run_once() is True

    with app.extensions["save_sync_connect"]() as db:
        versions = [
            row[0] for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
        pending = db.execute("SELECT count(*) FROM pending_backups").fetchone()[0]
    assert pending == 0
    assert versions == [2]
    assert not (storage / old_relative).exists()
    assert (storage / new_relative).is_file()


def test_controlled_supervisor_stop_kills_child_but_preserves_queue(tmp_path):
    app, storage, db_path = bootstrap_storage(tmp_path)
    queue_version(app, storage, 1)

    class HangingProcess:
        pid = 123456

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd=["restic"], timeout=timeout or 0)

    supervisor = make_supervisor(storage, db_path, lambda *a, **k: HangingProcess())
    killed = []

    def terminate(process, **_kwargs):
        killed.append(process.pid)

    supervisor.terminate_process_group = terminate
    supervisor.stop_requested = True
    # run_once llega a lanzar el proceso y wait_for_process observa la parada.
    assert supervisor.run_once() is True

    assert killed == [123456]
    with app.extensions["save_sync_connect"]() as db:
        assert db.execute("SELECT version FROM pending_backups").fetchone()[0] == 1
        completed = db.execute(
            "SELECT count(*) FROM audit "
            "WHERE event IN ('backup_hook_completed','backup_hook_failed')"
        ).fetchone()[0]
    assert completed == 0


def test_finalization_rollback_keeps_job_for_retry(tmp_path, monkeypatch):
    app, storage, db_path = bootstrap_storage(tmp_path)
    queue_version(app, storage, 1)
    supervisor = make_supervisor(storage, db_path, lambda *a, **k: SuccessfulProcess())

    original_connect = supervisor.connect

    class FailingConnection:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.wrapped.close()

        def execute(self, sql, params=()):
            if sql.startswith("INSERT INTO audit") and params[0] == "backup_hook_completed":
                raise sqlite3.OperationalError("auditoría no disponible")
            return self.wrapped.execute(sql, params)

        def commit(self):
            return self.wrapped.commit()

        def rollback(self):
            return self.wrapped.rollback()

    def failing_connect():
        return FailingConnection(original_connect())

    # Solo hacemos fallar finalización; start/lookup usan conexión normal.
    job = supervisor.next_job()
    assert supervisor.mark_attempt_started(job) is True
    monkeypatch.setattr(supervisor, "connect", failing_connect)
    try:
        supervisor.finalize_job(job, success=True, exit_code=0)
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("finalize_job debía propagar el fallo transaccional")

    with app.extensions["save_sync_connect"]() as db:
        assert db.execute("SELECT version FROM pending_backups").fetchone()[0] == 1
