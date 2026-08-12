import hashlib
import io
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from save_sync.app import create_app, digest, iso, utcnow

WORLD_GUID = "A7E97BAA767DB9029EF013BB71E993A0"
OTHER_WORLD_GUID = "B8F08CBB878EC013AF1024CC82FAA4B1"


def zip_payload(marker=b"save"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Pal/Saved/SaveGames/world.sav", marker)
    return stream.getvalue()


def headers(username="admin"):
    return {"Authorization": f"Bearer pws_{username}_test"}


def acquire(client):
    response = client.post(
        "/api/games/palworld/lock",
        headers=headers(),
        json={"owner": "Host A", "clientId": "debugger-pc"},
    )
    assert response.status_code == 201
    return response.get_json()


def upload(client, session, base, payload, save_identity=WORLD_GUID):
    return client.post(
        "/api/games/palworld/upload",
        headers=headers(),
        data={
            "file": (io.BytesIO(payload), "save.zip"),
            "sessionId": session,
            "baseVersion": str(base),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "worldGuid": save_identity,
        },
        content_type="multipart/form-data",
    )


def legacy_schema(path, *, save_identity_column=False):
    db = sqlite3.connect(path)
    db.executescript(
        f"""
        CREATE TABLE users (
          id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
          role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE api_tokens (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
          token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
          last_used_at TEXT, revoked_at TEXT
        );
        CREATE TABLE versions (
          version INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
          sha256 TEXT NOT NULL, size INTEGER NOT NULL, updated_by INTEGER NOT NULL,
          updated_at TEXT NOT NULL, base_version INTEGER NOT NULL,
          restored_from_version INTEGER
          {", save_identity TEXT" if save_identity_column else ""}
        );
        CREATE TABLE current_save (
          singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL
        );
        CREATE TABLE active_lock (
          singleton INTEGER PRIMARY KEY, session_hash TEXT NOT NULL UNIQUE,
          owner_user_id INTEGER NOT NULL, owner_label TEXT NOT NULL,
          client_id TEXT NOT NULL, base_version INTEGER NOT NULL,
          created_at TEXT NOT NULL, last_heartbeat_at TEXT NOT NULL,
          expires_at TEXT NOT NULL
        );
        CREATE TABLE audit (
          id INTEGER PRIMARY KEY, event TEXT NOT NULL, user_id INTEGER,
          at TEXT NOT NULL, success INTEGER NOT NULL, client_id TEXT,
          details TEXT NOT NULL DEFAULT '{{}}'
        );
        CREATE TABLE rate_limits (
          identity TEXT NOT NULL, window INTEGER NOT NULL, count INTEGER NOT NULL,
          PRIMARY KEY(identity, window)
        );
        """
    )
    db.close()


def app_config(storage):
    return {
        "TESTING": True,
        "SAVE_SYNC_STORAGE_PATH": str(storage),
        "SAVE_SYNC_DB_PATH": str(storage / "palworld.sqlite3"),
        "SAVE_SYNC_REQUIRE_HTTPS": False,
        "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
    }


def seed_tokens(app):
    with app.extensions["save_sync_connect"]() as db:
        users = db.execute("SELECT id,username FROM users").fetchall()
        for user in users:
            db.execute(
                "INSERT OR IGNORE INTO api_tokens"
                "(user_id,name,token_hash,created_at) VALUES(?,?,?,?)",
                (
                    user["id"],
                    "debugger",
                    digest(f"token-{user['username']}"),
                    iso(utcnow()),
                ),
            )


def test_legacy_uninitialized_migration_is_idempotent_with_two_workers(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    legacy_schema(storage / "palworld.sqlite3")

    with ThreadPoolExecutor(max_workers=2) as pool:
        apps = list(pool.map(lambda _: create_app(app_config(storage)), range(2)))

    # A third run demonstrates idempotence after the initial race.
    restarted = create_app(app_config(storage))
    with restarted.extensions["save_sync_connect"]() as db:
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(versions)").fetchall()
        }
        triggers = db.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='trigger' AND name LIKE '%save_identity%'"
        ).fetchone()[0]
    assert len(apps) == 2
    assert "save_identity" in columns
    assert triggers == 4


@pytest.mark.parametrize("bad_guid", [None, "invalid", "a" * 32])
def test_startup_fails_closed_if_any_legacy_version_has_bad_guid(tmp_path, bad_guid):
    storage = tmp_path / "storage"
    backups = storage / "backups"
    backups.mkdir(parents=True)
    db_path = storage / "palworld.sqlite3"
    legacy_schema(db_path, save_identity_column=True)
    db = sqlite3.connect(db_path)
    db.execute("INSERT INTO users(id,username,role) VALUES(1,'admin','admin')")
    for version, guid in ((1, bad_guid), (2, WORLD_GUID)):
        relative = f"backups/save-v{version:06d}.zip"
        Path(storage, relative).write_bytes(zip_payload(str(version).encode()))
        db.execute(
            "INSERT INTO versions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                version,
                relative,
                "0" * 64,
                1,
                1,
                iso(utcnow()),
                version - 1,
                None,
                guid,
            ),
        )
    db.execute("INSERT INTO current_save VALUES(1,2)")
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="save_identity"):
        create_app(app_config(storage))


def test_first_upload_fixes_guid_and_mismatch_preserves_everything(app):
    with app.test_client() as client:
        first_lock = acquire(client)
        first_payload = zip_payload(b"first")
        first = upload(
            client,
            first_lock["sessionId"],
            0,
            first_payload,
            WORLD_GUID.lower(),
        )
        assert first.status_code == 201
        assert first.get_json()["worldGuid"] == WORLD_GUID

        second_lock = acquire(client)
        before_status = client.get("/api/games/palworld/status", headers=headers()).get_json()
        backups = Path(app.config["SAVE_SYNC_STORAGE_PATH"], "backups")
        before_files = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in backups.glob("*.zip")
        }
        mismatch = upload(
            client,
            second_lock["sessionId"],
            1,
            zip_payload(b"wrong-world"),
            OTHER_WORLD_GUID,
        )
        after_status = client.get("/api/games/palworld/status", headers=headers()).get_json()
        after_files = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in backups.glob("*.zip")
        }

    assert mismatch.status_code == 409
    assert mismatch.get_json()["error"] == "world_guid_conflict"
    assert after_status["version"] == before_status["version"] == 1
    assert after_status["sha256"] == before_status["sha256"]
    assert after_status["worldGuid"] == before_status["worldGuid"] == WORLD_GUID
    assert after_status["locked"] is before_status["locked"] is True
    assert after_status["lock"] == before_status["lock"]
    assert after_files == before_files


def test_restore_rejects_historical_version_from_different_world(app):
    with app.test_client() as client:
        first_lock = acquire(client)
        assert (
            upload(
                client, first_lock["sessionId"], 0, zip_payload(b"current")
            ).status_code
            == 201
        )

    storage = Path(app.config["SAVE_SYNC_STORAGE_PATH"])
    foreign_path = "backups/save-v000099.zip"
    foreign_payload = zip_payload(b"foreign")
    Path(storage, foreign_path).write_bytes(foreign_payload)
    with app.extensions["save_sync_connect"]() as db:
        admin = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        db.execute(
            "INSERT INTO versions"
            "(version,path,sha256,size,updated_by,updated_at,base_version,save_identity) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                99,
                foreign_path,
                hashlib.sha256(foreign_payload).hexdigest(),
                len(foreign_payload),
                admin,
                iso(utcnow()),
                98,
                OTHER_WORLD_GUID,
            ),
        )

    with app.test_client() as client:
        response = client.post("/api/games/palworld/history/99/restore", headers=headers())
        status = client.get("/api/games/palworld/status", headers=headers()).get_json()
    assert response.status_code == 409
    assert response.get_json()["error"] == "world_guid_conflict"
    assert status["version"] == 1
    assert status["worldGuid"] == WORLD_GUID


def test_race_valid_and_foreign_world_has_deterministic_results(app):
    with app.test_client() as client:
        first_lock = acquire(client)
        assert (
            upload(client, first_lock["sessionId"], 0, zip_payload(b"v1")).status_code
            == 201
        )
        second_lock = acquire(client)

    def send(marker, guid):
        with app.test_client() as client:
            response = upload(
                client,
                second_lock["sessionId"],
                1,
                zip_payload(marker),
                guid,
            )
            return response.status_code, response.get_json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        valid_future = pool.submit(send, b"valid-v2", WORLD_GUID)
        foreign_future = pool.submit(send, b"foreign-v2", OTHER_WORLD_GUID)
        valid = valid_future.result(timeout=10)
        foreign = foreign_future.result(timeout=10)

    assert valid[0] == 201
    assert valid[1]["version"] == 2
    assert foreign[0] == 409
    assert foreign[1]["error"] == "world_guid_conflict"
    with app.extensions["save_sync_connect"]() as db:
        current = db.execute(
            "SELECT v.version,v.save_identity FROM current_save c "
            "JOIN versions v ON v.version=c.version"
        ).fetchone()
    assert tuple(current) == (2, WORLD_GUID)
