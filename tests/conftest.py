import hashlib
import io
import zipfile

import pytest

from save_sync import create_app

TOKENS = {"admin": "pws_admin_test", "player": "pws_player_test"}
OWNERS = {"admin": "Host A", "player": "Host B"}
WORLD_GUID = "A7E97BAA767DB9029EF013BB71E993A0"


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_STORAGE_PATH": str(tmp_path / "storage"),
            "SAVE_SYNC_DB_PATH": str(tmp_path / "storage" / "db.sqlite3"),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
            "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
            "SAVE_SYNC_MAX_UPLOAD_SIZE": 1024 * 1024,
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
            "SAVE_SYNC_LOCK_TTL_SECONDS": 300,
        }
    )
    connect = app.extensions["save_sync_connect"]
    with connect() as db:
        for username, token in TOKENS.items():
            user_id = db.execute(
                "SELECT id FROM users WHERE username=?", (username,)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO api_tokens(user_id,name,token_hash,created_at) VALUES(?,?,?,datetime('now'))",
                (user_id, "test", hashlib.sha256(token.encode()).hexdigest()),
            )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def auth(username="player"):
    return {"Authorization": f"Bearer {TOKENS[username]}"}


def zip_bytes(content=b"save-data"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Pal/Saved/SaveGames/world.sav", content)
    return output.getvalue()


def acquire(client, username="player", owner=None, client_id="pc-1"):
    return client.post(
        "/api/games/palworld/lock",
        headers=auth(username),
        json={"owner": owner or OWNERS[username], "clientId": client_id},
    )


def upload(
    client,
    session_id,
    base=0,
    data=None,
    username="player",
    claimed_hash=None,
    filename="save.zip",
    save_identity=WORLD_GUID,
):
    data = data if data is not None else zip_bytes()
    claimed_hash = claimed_hash or hashlib.sha256(data).hexdigest()
    return client.post(
        "/api/games/palworld/upload",
        headers=auth(username),
        data={
            "file": (io.BytesIO(data), filename),
            "sessionId": session_id,
            "baseVersion": str(base),
            "owner": username,
            "sha256": claimed_hash,
            "worldGuid": save_identity,
        },
    )


def initialize(client, username="player", content=b"initial"):
    lock = acquire(client, username=username).get_json()
    response = upload(
        client, lock["sessionId"], username=username, data=zip_bytes(content)
    )
    assert response.status_code == 201
    return response
