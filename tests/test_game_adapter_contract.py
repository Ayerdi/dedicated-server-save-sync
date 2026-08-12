import hashlib
import io
import json
import sqlite3
import zipfile

import pytest

from save_sync import create_app


def zip_bytes(marker):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("save/data.bin", marker)
    return output.getvalue()


def generic_app(tmp_path, game_key="example-game"):
    game_path = tmp_path / f"{game_key}.json"
    game_path.write_text(
        json.dumps(
            {
                "key": game_key,
                "displayName": "Example Game",
                "identityField": "campaignId",
                "identityLabel": "Campaign ID",
                "identityPattern": "^[a-z0-9-]{3,64}$",
                "identityNormalization": "lowercase",
                "legacyPalworldRoutes": False,
            }
        ),
        encoding="utf-8",
    )
    storage = tmp_path / "storage"
    app = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_GAME_KEY": game_key,
            "SAVE_SYNC_GAME_CONFIG_PATH": str(game_path),
            "SAVE_SYNC_STORAGE_PATH": str(storage),
            "SAVE_SYNC_DB_PATH": str(storage / "save-sync.sqlite3"),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_WEB_USERS": "operator:admin",
            "SAVE_SYNC_USER_IDENTITIES_JSON": (
                '{"operator":{"displayName":"Example Host","slot":"host-one"}}'
            ),
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
        }
    )
    token = "pws_generic_test"
    with app.extensions["save_sync_connect"]() as db:
        user_id = db.execute(
            "SELECT id FROM users WHERE username='operator'"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO api_tokens(user_id,name,token_hash,created_at) "
            "VALUES(?,?,?,datetime('now'))",
            (user_id, "test", hashlib.sha256(token.encode()).hexdigest()),
        )
    return app, token


def test_generic_game_uses_configured_identity_and_canonical_routes(tmp_path):
    app, token = generic_app(tmp_path)
    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    empty = client.get("/api/games/example-game/status", headers=headers)
    assert empty.status_code == 200
    assert empty.get_json()["identityField"] == "campaignId"
    assert empty.get_json()["saveIdentity"] is None
    assert "worldGuid" not in empty.get_json()
    assert client.get("/api/palworld/status", headers=headers).status_code == 404

    lock = client.post(
        "/api/games/example-game/lock",
        headers=headers,
        json={"owner": "Example Host", "clientId": "example-pc"},
    ).get_json()
    payload = zip_bytes(b"example")
    response = client.post(
        "/api/games/example-game/upload",
        headers=headers,
        data={
            "file": (io.BytesIO(payload), "save.zip"),
            "sessionId": lock["sessionId"],
            "baseVersion": "0",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "campaignId": "CAMPAIGN-ONE",
        },
    )
    assert response.status_code == 201
    assert response.get_json()["saveIdentity"] == "campaign-one"
    assert response.get_json()["campaignId"] == "campaign-one"

    download = client.get("/api/games/example-game/download", headers=headers)
    assert download.headers["X-Save-Sync-Identity"] == "campaign-one"
    assert "X-Palworld-World-Guid" not in download.headers

    second_lock = client.post(
        "/api/games/example-game/lock",
        headers=headers,
        json={"owner": "Example Host", "clientId": "example-pc"},
    ).get_json()
    conflict_payload = zip_bytes(b"other-campaign")
    conflict = client.post(
        "/api/games/example-game/upload",
        headers=headers,
        data={
            "file": (io.BytesIO(conflict_payload), "save.zip"),
            "sessionId": second_lock["sessionId"],
            "baseVersion": "1",
            "sha256": hashlib.sha256(conflict_payload).hexdigest(),
            "campaignId": "other-campaign",
        },
    )
    assert conflict.status_code == 409
    assert conflict.get_json()["error"] == "save_identity_conflict"


def test_game_key_must_match_adapter_file(tmp_path):
    game_path = tmp_path / "game.json"
    game_path.write_text(
        json.dumps(
            {
                "key": "configured-game",
                "displayName": "Configured Game",
                "identityField": "saveId",
                "identityLabel": "Save ID",
                "identityPattern": "^[a-z]+$",
                "identityNormalization": "none",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="does not match"):
        create_app(
            {
                "TESTING": True,
                "SAVE_SYNC_GAME_KEY": "other-game",
                "SAVE_SYNC_GAME_CONFIG_PATH": str(game_path),
            }
        )


def test_palworld_v1_database_requires_separate_v2_storage(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    db_path = storage / "save-sync.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE versions ("
            "version INTEGER PRIMARY KEY,path TEXT NOT NULL UNIQUE,"
            "sha256 TEXT NOT NULL,size INTEGER NOT NULL,updated_by INTEGER NOT NULL,"
            "updated_at TEXT NOT NULL,base_version INTEGER NOT NULL,"
            "restored_from_version INTEGER,world_guid TEXT NOT NULL)"
        )

    with pytest.raises(RuntimeError, match="separate storage"):
        create_app(
            {
                "TESTING": True,
                "SAVE_SYNC_STORAGE_PATH": str(storage),
                "SAVE_SYNC_DB_PATH": str(db_path),
            }
        )
