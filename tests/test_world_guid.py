import concurrent.futures
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from conftest import WORLD_GUID, acquire, auth, initialize, upload, zip_bytes
from save_sync import create_app


OTHER_WORLD_GUID = "B8F08CBB878ECA13AF1024CC82FAA4B1"


def test_uninitialized_status_has_null_save_identity(client):
    response = client.get("/api/games/palworld/status", headers=auth())
    assert response.status_code == 200
    assert response.get_json()["worldGuid"] is None


def test_first_upload_establishes_authoritative_save_identity(client):
    response = initialize(client)
    assert response.get_json()["worldGuid"] == WORLD_GUID
    history = client.get("/api/games/palworld/history", headers=auth()).get_json()
    assert history["versions"][0]["worldGuid"] == WORLD_GUID


def test_initialized_status_and_lock_return_save_identity(client):
    initialize(client)
    status = client.get("/api/games/palworld/status", headers=auth()).get_json()
    assert status["worldGuid"] == WORLD_GUID
    acquired = acquire(client).get_json()
    assert acquired["worldGuid"] == WORLD_GUID


def test_latest_and_historical_downloads_have_save_identity_header(client):
    initialize(client, username="player")
    latest = client.get("/api/games/palworld/download", headers=auth())
    historical = client.get("/api/games/palworld/history/1/download", headers=auth("admin"))
    assert latest.headers["X-Palworld-World-Guid"] == WORLD_GUID
    assert historical.headers["X-Palworld-World-Guid"] == WORLD_GUID


def test_second_upload_accepts_same_save_identity(client):
    initialize(client)
    acquired = acquire(client).get_json()
    response = upload(client, acquired["sessionId"], base=1)
    assert response.status_code == 201
    assert response.get_json()["worldGuid"] == WORLD_GUID


def test_different_save_identity_is_stable_conflict(client):
    initialize(client)
    acquired = acquire(client).get_json()
    response = upload(
        client, acquired["sessionId"], base=1, save_identity=OTHER_WORLD_GUID
    )
    assert response.status_code == 409
    assert response.get_json() == {
        "error": "world_guid_conflict",
        "message": "El ZIP pertenece a un mundo de Palworld diferente.",
        "details": {
            "identityField": "worldGuid",
            "expectedSaveIdentity": WORLD_GUID,
            "receivedSaveIdentity": OTHER_WORLD_GUID,
            "expectedWorldGuid": WORLD_GUID,
            "receivedWorldGuid": OTHER_WORLD_GUID,
        },
    }


@pytest.mark.parametrize("save_identity", ["", "not-a-guid", "A" * 31, "G" * 32])
def test_empty_or_invalid_save_identity_is_rejected(client, save_identity):
    acquired = acquire(client).get_json()
    response = upload(client, acquired["sessionId"], save_identity=save_identity)
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_save_identity"


def test_lowercase_save_identity_is_normalized(client):
    acquired = acquire(client).get_json()
    response = upload(client, acquired["sessionId"], save_identity=WORLD_GUID.lower())
    assert response.status_code == 201
    assert response.get_json()["worldGuid"] == WORLD_GUID
    status = client.get("/api/games/palworld/status", headers=auth()).get_json()
    assert status["worldGuid"] == WORLD_GUID


def test_save_identity_conflict_preserves_version_zip_and_lock(client, app):
    initialize(client, content=b"original")
    before = client.get("/api/games/palworld/download", headers=auth()).data
    acquired = acquire(client).get_json()
    response = upload(
        client,
        acquired["sessionId"],
        base=1,
        data=zip_bytes(b"wrong-world"),
        save_identity=OTHER_WORLD_GUID,
    )
    assert response.status_code == 409
    after = client.get("/api/games/palworld/download", headers=auth()).data
    status = client.get("/api/games/palworld/status", headers=auth()).get_json()
    assert after == before
    assert status["version"] == 1
    assert status["worldGuid"] == WORLD_GUID
    assert status["locked"] is True
    with app.extensions["save_sync_connect"]() as db:
        assert db.execute("SELECT count(*) FROM versions").fetchone()[0] == 1
        event = db.execute(
            "SELECT details FROM audit WHERE event='world_guid_conflict' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    details = json.loads(event["details"])
    assert details["expectedWorldGuid"] == WORLD_GUID
    assert details["receivedWorldGuid"] == OTHER_WORLD_GUID


def test_history_returns_save_identity(client):
    initialize(client)
    versions = client.get("/api/games/palworld/history", headers=auth()).get_json()[
        "versions"
    ]
    assert versions == [
        {
            **versions[0],
            "worldGuid": WORLD_GUID,
        }
    ]


def test_restore_preserves_save_identity(client):
    initialize(client, username="player", content=b"v1")
    acquired = acquire(client, "admin", "Host A", "admin-pc").get_json()
    assert (
        upload(
            client,
            acquired["sessionId"],
            base=1,
            username="admin",
            data=zip_bytes(b"v2"),
        ).status_code
        == 201
    )
    restored = client.post("/api/games/palworld/history/1/restore", headers=auth("admin"))
    assert restored.status_code == 201
    assert restored.get_json()["worldGuid"] == WORLD_GUID
    assert (
        client.get("/api/games/palworld/status", headers=auth()).get_json()["worldGuid"]
        == WORLD_GUID
    )


def test_palworld_audit_events_include_world_guid(client, app):
    initialize(client)
    acquired = acquire(client).get_json()
    conflict = upload(client, acquired["sessionId"], base=0)
    assert conflict.status_code == 409
    assert client.post(
        "/api/games/palworld/unlock",
        headers=auth(),
        json={"sessionId": acquired["sessionId"]},
    ).status_code == 200
    assert client.post(
        "/api/games/palworld/history/1/restore", headers=auth("admin")
    ).status_code == 201

    with app.extensions["save_sync_connect"]() as db:
        rows = db.execute(
            "SELECT event,details FROM audit WHERE event IN "
            "('upload_completed','version_conflict','backup_restored')"
        ).fetchall()
    by_event = {row["event"]: json.loads(row["details"]) for row in rows}
    assert by_event["upload_completed"]["worldGuid"] == WORLD_GUID
    assert by_event["version_conflict"]["worldGuid"] == WORLD_GUID
    assert by_event["backup_restored"]["worldGuid"] == WORLD_GUID


def test_restore_rejects_historical_version_from_other_world(client, app):
    initialize(client)
    with app.extensions["save_sync_connect"]() as db:
        user_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        db.execute(
            "INSERT INTO versions(version,path,sha256,size,updated_by,updated_at,"
            "base_version,restored_from_version,save_identity) "
            "VALUES(2,'backups/save-v000002.zip',?,1,?,'2026-01-01T00:00:00Z',1,NULL,?)",
            (hashlib.sha256(b"x").hexdigest(), user_id, OTHER_WORLD_GUID),
        )
    response = client.post("/api/games/palworld/history/2/restore", headers=auth("admin"))
    assert response.status_code == 409
    assert response.get_json()["error"] == "world_guid_conflict"
    status = client.get("/api/games/palworld/status", headers=auth()).get_json()
    assert status["version"] == 1
    assert status["worldGuid"] == WORLD_GUID


def test_invalid_save_identity_echo_is_bounded(client):
    acquired = acquire(client).get_json()
    response = upload(client, acquired["sessionId"], save_identity="A" * 10000)
    assert response.status_code == 400
    assert len(response.get_json()["details"]["receivedWorldGuid"]) == 128


def create_legacy_database(path, initialized=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE versions (
              version INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
              sha256 TEXT NOT NULL, size INTEGER NOT NULL, updated_by INTEGER NOT NULL,
              updated_at TEXT NOT NULL, base_version INTEGER NOT NULL,
              restored_from_version INTEGER
            );
            CREATE TABLE current_save (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL
            );
            """
        )
        if initialized:
            db.execute(
                "INSERT INTO versions VALUES(1,'backups/save-v000001.zip',?,?,1,?,0,NULL)",
                (hashlib.sha256(b"legacy").hexdigest(), 6, "2026-01-01T00:00:00Z"),
            )
            db.execute("INSERT INTO current_save VALUES(1,1)")


def app_config(storage):
    return {
        "TESTING": True,
        "SAVE_SYNC_STORAGE_PATH": str(storage),
        "SAVE_SYNC_DB_PATH": str(storage / "db.sqlite3"),
        "SAVE_SYNC_REQUIRE_HTTPS": False,
        "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
    }


def test_migration_is_idempotent_for_uninitialized_installation(tmp_path):
    storage = tmp_path / "storage"
    create_legacy_database(storage / "db.sqlite3")
    create_app(app_config(storage))
    create_app(app_config(storage))
    with sqlite3.connect(storage / "db.sqlite3") as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(versions)")}
        triggers = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
    assert "save_identity" in columns
    assert "versions_save_identity_insert" in triggers
    assert "current_save_save_identity_update" in triggers


def test_migration_is_serialized_between_two_workers(tmp_path):
    storage = tmp_path / "storage"
    create_legacy_database(storage / "db.sqlite3")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        applications = list(
            pool.map(lambda _: create_app(app_config(storage)), range(2))
        )
    assert len(applications) == 2
    with sqlite3.connect(storage / "db.sqlite3") as db:
        assert [row[1] for row in db.execute("PRAGMA table_info(versions)")].count(
            "save_identity"
        ) == 1


def test_migration_fails_closed_for_initialized_legacy_installation(tmp_path):
    storage = tmp_path / "storage"
    create_legacy_database(storage / "db.sqlite3", initialized=True)
    with pytest.raises(RuntimeError, match="sin save_identity válido"):
        create_app(app_config(storage))


def test_migration_fails_closed_for_orphan_legacy_history(tmp_path):
    storage = tmp_path / "storage"
    create_legacy_database(storage / "db.sqlite3", initialized=True)
    with sqlite3.connect(storage / "db.sqlite3") as db:
        db.execute("DELETE FROM current_save")
    with pytest.raises(RuntimeError, match="sin save_identity válido"):
        create_app(app_config(storage))


def test_concurrent_upload_with_wrong_world_has_one_publication(app):
    client = app.test_client()
    initialize(client)
    acquired = acquire(client).get_json()
    before_paths = set(
        Path(app.config["SAVE_SYNC_STORAGE_PATH"], "backups").glob("*.zip")
    )

    def attempt(save_identity):
        return upload(
            app.test_client(),
            acquired["sessionId"],
            base=1,
            data=zip_bytes(save_identity.encode()),
            save_identity=save_identity,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(attempt, [WORLD_GUID, OTHER_WORLD_GUID]))
    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.get_json()["error"] == "world_guid_conflict"
    status = client.get("/api/games/palworld/status", headers=auth()).get_json()
    assert status["version"] == 2
    assert status["worldGuid"] == WORLD_GUID
    after_paths = set(
        Path(app.config["SAVE_SYNC_STORAGE_PATH"], "backups").glob("*.zip")
    )
    assert len(after_paths) <= 2
    assert before_paths <= after_paths or len(after_paths) == 1
