import concurrent.futures
import hashlib
import hmac
import io
import json
from datetime import datetime, timedelta, timezone

from conftest import acquire, auth, initialize, upload, zip_bytes


def test_01_first_upload_over_zero(client):
    response = initialize(client)
    assert response.get_json()["version"] == 1
    status = client.get("/api/games/palworld/status", headers=auth()).get_json()
    assert status["initialized"] is True
    assert status["updatedBy"] == "Host B"
    history = client.get("/api/games/palworld/history", headers=auth()).get_json()
    assert history["versions"][0]["updatedBy"] == "Host B"


def test_02_download_latest(client):
    initialize(client)
    response = client.get("/api/games/palworld/download", headers=auth())
    assert response.status_code == 200
    assert response.headers["X-Palworld-Version"] == "1"
    assert (
        hashlib.sha256(response.data).hexdigest()
        == response.headers["X-Palworld-SHA256"]
    )


def test_03_acquire_lock(client):
    response = acquire(client)
    assert response.status_code == 201
    assert response.get_json()["baseVersion"] == 0


def test_palworld_legacy_api_alias_remains_available(client):
    response = client.get("/api/palworld/status", headers=auth())
    assert response.status_code == 200
    assert response.get_json()["gameKey"] == "palworld"
    assert response.get_json()["worldGuid"] is None


def test_backup_status_requires_auth_and_reports_disabled_state(client):
    endpoint = "/api/games/palworld/backup-status"
    assert client.get(endpoint).status_code == 401

    empty = client.get(endpoint, headers=auth()).get_json()
    assert empty["state"] == "not_initialized"
    assert empty["latestPublishedVersion"] == 0
    assert empty["latestVersionBackedUp"] is False

    initialize(client)
    disabled = client.get(endpoint, headers=auth()).get_json()
    assert disabled["enabled"] is False
    assert disabled["state"] == "disabled"
    assert disabled["latestPublishedVersion"] == 1


def test_backup_status_reports_pending_failure_and_completion(app):
    client = app.test_client()
    initialize(client)
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"
    endpoint = "/api/games/palworld/backup-status"

    unknown = client.get(endpoint, headers=auth()).get_json()
    assert unknown["state"] == "unknown"

    connect = app.extensions["save_sync_connect"]
    with connect() as db:
        db.execute(
            "INSERT INTO pending_backups(version,started_at) VALUES(?,?)",
            (1, "2026-08-12T10:00:00Z"),
        )
    pending = client.get(endpoint, headers=auth()).get_json()
    assert pending["state"] == "pending"
    assert pending["pending"] is True
    assert pending["stalePending"] is False
    assert pending["pendingVersions"] == [
        {"version": 1, "startedAt": "2026-08-12T10:00:00Z"}
    ]
    assert pending["stalePendingVersions"] == []

    with connect() as db:
        db.execute("DELETE FROM pending_backups WHERE version=1")
        db.execute(
            "INSERT INTO audit(event,at,success,details) VALUES(?,?,?,?)",
            (
                "backup_hook_failed",
                "2026-08-12T10:01:00Z",
                0,
                json.dumps(
                    {"version": 1, "exitCode": 12, "timedOut": 0}
                ),
            ),
        )
    failed = client.get(endpoint, headers=auth()).get_json()
    assert failed["state"] == "failed"
    assert failed["latestVersionBackedUp"] is False
    assert failed["lastAttempt"]["exitCode"] == 12
    assert failed["lastCompleted"] is None

    with connect() as db:
        db.execute(
            "INSERT INTO audit(event,at,success,details) VALUES(?,?,?,?)",
            (
                "backup_hook_completed",
                "2026-08-12T10:02:00Z",
                1,
                json.dumps({"version": 1, "exitCode": 0, "timedOut": 0}),
            ),
        )
    completed = client.get(endpoint, headers=auth()).get_json()
    assert completed["state"] == "completed"
    assert completed["latestVersionBackedUp"] is True
    assert completed["lastAttempt"] == completed["lastCompleted"]
    assert completed["lastCompleted"]["completedAt"] == "2026-08-12T10:02:00Z"


def test_backup_status_treats_stale_pending_as_unknown_without_mutating_db(app):
    client = app.test_client()
    initialize(client)
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"
    endpoint = "/api/games/palworld/backup-status"
    stale_started = (
        datetime.now(timezone.utc)
        - timedelta(
            seconds=int(app.config["SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS"]) + 61
        )
    ).isoformat().replace("+00:00", "Z")

    connect = app.extensions["save_sync_connect"]
    with connect() as db:
        db.execute(
            "INSERT INTO pending_backups(version,started_at) VALUES(?,?)",
            (1, stale_started),
        )

    snapshot = client.get(endpoint, headers=auth()).get_json()
    assert snapshot["state"] == "unknown"
    assert snapshot["pending"] is False
    assert snapshot["pendingVersions"] == []
    assert snapshot["stalePending"] is True
    assert snapshot["stalePendingVersions"] == [
        {"version": 1, "startedAt": stale_started}
    ]

    with connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM pending_backups WHERE version=1"
        ).fetchone()[0] == 1


def test_04_second_user_lock_is_conflict(client):
    assert acquire(client).status_code == 201
    response = acquire(client, "admin", "Host A", "pc-2")
    assert response.status_code == 409
    assert response.get_json()["error"] == "lock_occupied"


def test_05_valid_heartbeat(client):
    sid = acquire(client).get_json()["sessionId"]
    response = client.post(
        "/api/games/palworld/heartbeat", headers=auth(), json={"sessionId": sid}
    )
    assert response.status_code == 200 and response.get_json()["ok"]


def test_06_wrong_heartbeat_session(client):
    acquire(client)
    response = client.post(
        "/api/games/palworld/heartbeat", headers=auth(), json={"sessionId": "wrong"}
    )
    assert (
        response.status_code == 409
        and response.get_json()["error"] == "invalid_session"
    )


def test_07_expired_lock_can_be_reacquired(app):
    first = app.test_client()
    assert acquire(first).status_code == 201
    with app.extensions["save_sync_connect"]() as db:
        expired = (
            (datetime.now(timezone.utc) - timedelta(seconds=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        db.execute("UPDATE active_lock SET expires_at=?", (expired,))
    assert acquire(app.test_client(), "admin", "Host A", "pc-2").status_code == 201


def test_08_voluntary_unlock(client):
    sid = acquire(client).get_json()["sessionId"]
    assert (
        client.post(
            "/api/games/palworld/unlock", headers=auth(), json={"sessionId": sid}
        ).status_code
        == 200
    )
    assert acquire(client, "admin", "Host A", "pc-2").status_code == 201


def test_09_upload_on_base_version(client):
    initialize(client)
    lock = acquire(client).get_json()
    assert lock["baseVersion"] == 1
    assert upload(client, lock["sessionId"], base=1).get_json()["version"] == 2


def test_10_wrong_sha(client):
    sid = acquire(client).get_json()["sessionId"]
    response = upload(client, sid, claimed_hash="0" * 64)
    assert (
        response.status_code == 422
        and response.get_json()["error"] == "sha256_mismatch"
    )


def test_11_non_zip(client):
    sid = acquire(client).get_json()["sessionId"]
    response = upload(client, sid, data=b"not-a-zip", filename="save.zip")
    assert response.status_code == 422 and response.get_json()["error"] == "zip_invalid"


def test_12_too_large(client, app):
    app.config["SAVE_SYNC_MAX_UPLOAD_SIZE"] = 8
    sid = acquire(client).get_json()["sessionId"]
    response = upload(client, sid, data=b"x" * 9)
    assert response.status_code == 413


def test_13_concurrent_lock_has_one_winner(app):
    def attempt(username):
        return acquire(
            app.test_client(), username, None, username + "-pc"
        ).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(attempt, ["admin", "player"]))
    assert sorted(statuses) == [201, 409]


def test_14_version_conflict(client, app):
    initialize(client)
    sid = acquire(client).get_json()["sessionId"]
    with app.extensions["save_sync_connect"]() as db:
        db.execute("UPDATE active_lock SET base_version=0")
    response = upload(client, sid, base=0)
    assert (
        response.status_code == 409
        and response.get_json()["error"] == "version_conflict"
    )


def test_15_failed_upload_preserves_previous(client):
    initialize(client)
    before = client.get("/api/games/palworld/download", headers=auth()).data
    sid = acquire(client).get_json()["sessionId"]
    assert upload(client, sid, base=1, data=b"broken").status_code == 422
    after = client.get("/api/games/palworld/download", headers=auth()).data
    assert after == before


def test_16_download_without_auth(client):
    assert client.get("/api/games/palworld/download").status_code == 401


def test_17_player_cannot_restore(client):
    initialize(client)
    assert (
        client.post("/api/games/palworld/history/1/restore", headers=auth()).status_code
        == 403
    )


def test_18_admin_restore_creates_new_version(client):
    initialize(client)
    response = client.post("/api/games/palworld/history/1/restore", headers=auth("admin"))
    assert response.status_code == 201
    assert response.get_json()["version"] == 2
    assert response.get_json()["restoredFromVersion"] == 1


def test_19_same_player_player_keeps_only_latest_canonical_version(client):
    initialize(client)
    for base in range(1, 5):
        sid = acquire(client).get_json()["sessionId"]
        assert (
            upload(
                client, sid, base=base, data=zip_bytes(str(base).encode())
            ).status_code
            == 201
        )
    versions = client.get("/api/games/palworld/history", headers=auth()).get_json()[
        "versions"
    ]
    assert [v["version"] for v in versions] == [5]


def test_20_storage_not_public(client):
    initialize(client)
    assert client.get("/backups/save-v000001.zip").status_code == 404
    assert client.get("/palworld/backups/save-v000001.zip").status_code == 404


def test_concurrent_upload_only_one_publishes(app):
    base_client = app.test_client()
    initialize(base_client)
    lock = acquire(base_client).get_json()
    sid = lock["sessionId"]
    payload = zip_bytes(b"race")

    def attempt():
        return upload(app.test_client(), sid, base=1, data=payload).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: attempt(), range(2)))
    assert statuses.count(201) == 1
    assert statuses.count(409) == 1
    status = base_client.get("/api/games/palworld/status", headers=auth()).get_json()
    assert status["version"] == 2


def test_zip_traversal_rejected(client):
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("../evil", "x")
    sid = acquire(client).get_json()["sessionId"]
    response = upload(client, sid, data=out.getvalue())
    assert (
        response.status_code == 422
        and response.get_json()["error"] == "zip_unsafe_path"
    )


def test_web_requires_proxy_secret_and_csrf(client):
    assert (
        client.get("/games/palworld", headers={"X-authentik-username": "admin"}).status_code
        == 401
    )
    web = {
        "X-authentik-username": "admin",
        "X-Palworld-Proxy-Secret": "proxy-test-secret",
    }
    assert client.get("/games/palworld", headers=web).status_code == 200
    assert (
        client.post("/games/palworld/api/admin/force-unlock", headers=web).status_code == 403
    )
    csrf = hmac.new(b"csrf-test-secret", b"palworld:admin", hashlib.sha256).hexdigest()
    web["X-CSRF-Token"] = csrf
    response = client.post(
        "/games/palworld/api/admin/force-unlock",
        headers=web,
        json={"reason": "Prueba automatizada"},
    )
    assert response.status_code == 200


def test_web_authenticated_user_outside_allowlist_is_forbidden(client):
    headers = {
        "X-authentik-username": "Hawko",
        "X-Palworld-Proxy-Secret": "proxy-test-secret",
    }
    response = client.get("/games/palworld/api/status", headers=headers)
    assert response.status_code == 403
    assert response.get_json() == {
        "error": "web_user_not_allowed",
        "message": "El usuario autenticado no está autorizado para Palworld.",
        "details": {},
    }


def test_panel_escapes_api_values_used_in_inner_html(client):
    malicious_name = '<img src=x onerror="alert(1)">'
    created = client.post(
        "/api/games/palworld/admin/tokens",
        headers=auth("admin"),
        json={"username": "player", "name": malicious_name},
    )
    assert created.status_code == 201
    web_headers = {
        "X-authentik-username": "admin",
        "X-Palworld-Proxy-Secret": "proxy-test-secret",
    }
    panel = client.get("/games/palworld", headers=web_headers).get_data(as_text=True)
    assert malicious_name not in panel
    assert "${esc(t.name)}" in panel
    assert "${esc(t.username)}" in panel
    assert "${esc(v.updatedBy)}" in panel
    assert "${esc(v.updatedAt)}" in panel
    assert "${esc(v.sha256)}" in panel
    assert "${esc(x[1])}" in panel
    assert "${t.name}" not in panel
    assert "catch(()=>null)" in panel
    assert "Estado: no disponible" in panel


def test_api_ignores_forged_authentik_headers(client):
    headers = {
        "X-authentik-username": "admin",
        "X-Palworld-Proxy-Secret": "proxy-test-secret",
    }
    assert client.get("/api/games/palworld/status", headers=headers).status_code == 401


def test_zip_symlink_rejected(client):
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        entry = zipfile.ZipInfo("link")
        entry.external_attr = 0o120777 << 16
        archive.writestr(entry, "target")
    sid = acquire(client).get_json()["sessionId"]
    assert (
        upload(client, sid, data=out.getvalue()).get_json()["error"]
        == "zip_special_file"
    )


def test_zip_duplicate_rejected(client):
    import warnings
    import zipfile

    out = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(out, "w") as archive:
        warnings.simplefilter("ignore")
        archive.writestr("same", "a")
        archive.writestr("same", "b")
    sid = acquire(client).get_json()["sessionId"]
    assert (
        upload(client, sid, data=out.getvalue()).get_json()["error"]
        == "zip_duplicate_entry"
    )
