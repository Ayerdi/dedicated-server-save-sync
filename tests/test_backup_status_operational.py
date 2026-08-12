import json

from conftest import auth, initialize


def test_backup_status_separates_current_result_from_hook_enabled(app):
    client = app.test_client()
    initialize(client)
    endpoint = "/api/games/palworld/backup-status"
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"

    connect = app.extensions["save_sync_connect"]
    with connect() as db:
        db.execute(
            "INSERT INTO audit(event,at,success,details) VALUES(?,?,?,?)",
            (
                "backup_hook_completed",
                "2026-08-12T10:00:00Z",
                1,
                json.dumps({"version": 1, "exitCode": 0, "timedOut": 0}),
            ),
        )

    enabled = client.get(endpoint, headers=auth()).get_json()
    assert enabled["enabled"] is True
    assert enabled["state"] == "completed"
    assert enabled["latestVersionBackedUp"] is True

    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = ""
    disabled = client.get(endpoint, headers=auth()).get_json()
    assert disabled["enabled"] is False
    assert disabled["state"] == "completed"
    assert disabled["latestVersionBackedUp"] is True

    web_headers = {
        "X-authentik-username": "admin",
        "X-Palworld-Proxy-Secret": "proxy-test-secret",
    }
    panel = client.get("/games/palworld", headers=web_headers).get_data(as_text=True)
    assert 'id="backupConfig"' in panel
    assert "Automatic backup: ${b.enabled?'enabled':'disabled ⚠'}" in panel
    assert "Current version backup state:" in panel


def test_backup_status_finds_last_completed_beyond_500_failures(app):
    client = app.test_client()
    initialize(client)
    app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"] = "restic backup /data/save-sync"

    connect = app.extensions["save_sync_connect"]
    with connect() as db:
        db.execute(
            "INSERT INTO audit(event,at,success,details) VALUES(?,?,?,?)",
            (
                "backup_hook_completed",
                "2026-08-12T09:00:00Z",
                1,
                json.dumps({"version": 1, "exitCode": 0, "timedOut": 0}),
            ),
        )
        db.executemany(
            "INSERT INTO audit(event,at,success,details) VALUES(?,?,?,?)",
            [
                (
                    "backup_hook_failed",
                    f"2026-08-12T10:{index // 60:02d}:{index % 60:02d}Z",
                    0,
                    json.dumps(
                        {"version": 1, "exitCode": index + 1, "timedOut": 0}
                    ),
                )
                for index in range(501)
            ],
        )

    snapshot = client.get(
        "/api/games/palworld/backup-status", headers=auth()
    ).get_json()
    assert snapshot["state"] == "failed"
    assert snapshot["latestVersionBackedUp"] is False
    assert snapshot["lastAttempt"]["success"] is False
    assert snapshot["lastAttempt"]["exitCode"] == 501
    assert snapshot["lastCompleted"]["success"] is True
    assert snapshot["lastCompleted"]["version"] == 1
    assert snapshot["lastCompleted"]["completedAt"] == "2026-08-12T09:00:00Z"
