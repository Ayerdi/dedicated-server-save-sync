import hashlib
import sqlite3
from pathlib import Path

import pytest
from conftest import TOKENS, auth

from save_sync import create_app
from save_sync.app import SCHEMA_VERSION
from save_sync.managed import extract_client_ip

ROOT = Path(__file__).resolve().parents[1]
API = "/api/games/valheim"

VALHEIM_CONFIG = {
    "TESTING": True,
    "SAVE_SYNC_GAME_KEY": "valheim",
    "SAVE_SYNC_GAME_CONFIG_PATH": str(ROOT / "config/games/valheim.json"),
    "SAVE_SYNC_REQUIRE_HTTPS": False,
    "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
    "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
    "SAVE_SYNC_MAX_UPLOAD_SIZE": 1024 * 1024,
    "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
    "SAVE_SYNC_LOCK_TTL_SECONDS": 300,
    # Explicit proxy ranges for tests (loopback + private lab ranges).
    "SAVE_SYNC_TRUSTED_PROXY_CIDRS": (
        "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    ),
    "SAVE_SYNC_WEB_USERS": "admin:admin,player:player",
    "SAVE_SYNC_USER_IDENTITIES_JSON": (
        '{"admin":{"displayName":"Alex","slot":"alex"},'
        '"player":{"displayName":"Sofia","slot":"sofia"},'
        '"gamer":{"displayName":"Gamer","slot":"gamer"}}'
    ),
}


@pytest.fixture
def mapp(tmp_path, monkeypatch):
    monkeypatch.setenv("SAVE_SYNC_PUBLIC_BASE_URL", "https://sync.example.com")
    storage = tmp_path / "valheim-presence"
    storage.mkdir()
    config = dict(
        VALHEIM_CONFIG,
        SAVE_SYNC_STORAGE_PATH=str(storage),
        SAVE_SYNC_DB_PATH=str(storage / "save-sync.sqlite3"),
    )
    application = create_app(config)
    with application.extensions["save_sync_connect"]() as db:
        for username, token in TOKENS.items():
            user_id = db.execute(
                "SELECT id FROM users WHERE username=?", (username,)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO api_tokens(user_id,name,token_hash,created_at) "
                "VALUES(?,?,?,datetime('now'))",
                (user_id, "test", hashlib.sha256(token.encode()).hexdigest()),
            )
    return application


@pytest.fixture
def mclient(mapp):
    return mapp.test_client()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def create_host_token(mclient, username="gamer", client_id="gamer-pc"):
    response = mclient.post(
        f"{API}/admin/users",
        headers=auth("admin"),
        json={
            "username": username,
            "displayName": username.title(),
            "slot": username,
            "role": "player",
        },
    )
    assert response.status_code == 201
    user_id = response.get_json()["id"]
    response = mclient.post(
        f"{API}/admin/hosts",
        headers=auth("admin"),
        json={"userId": user_id, "clientId": client_id, "name": f"{username} pc"},
    )
    assert response.status_code == 201
    host_id = response.get_json()["id"]
    response = mclient.post(
        f"{API}/admin/tokens",
        headers=auth("admin"),
        json={"username": username, "hostId": host_id, "name": f"{client_id}-token"},
    )
    assert response.status_code == 201
    body = response.get_json()
    return body["token"], host_id


def lock_as(mclient, token, owner="Gamer", client_id="gamer-pc", headers=None, **kwargs):
    merged = dict(bearer(token))
    merged.update(headers or {})
    return mclient.post(
        f"{API}/lock",
        headers=merged,
        json={"owner": owner, "clientId": client_id},
        **kwargs,
    )


def test_schema_four_migrates_last_ip(tmp_path):
    storage = tmp_path / "schema4"
    storage.mkdir()
    db_path = storage / "save-sync.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            PRAGMA user_version=4;
            CREATE TABLE users (
              id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
              role TEXT NOT NULL CHECK(role IN ('admin','player')),
              active INTEGER NOT NULL DEFAULT 1, display_name TEXT, slot TEXT
            );
            CREATE TABLE authorized_hosts (
              id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
              client_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
              created_at TEXT NOT NULL, last_seen_at TEXT, last_published_at TEXT
            );
            CREATE TABLE api_tokens (
              id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
              name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT,
              host_id INTEGER REFERENCES authorized_hosts(id)
            );
            CREATE TABLE versions (
              version INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL,
              size INTEGER NOT NULL, updated_by INTEGER NOT NULL REFERENCES users(id),
              updated_at TEXT NOT NULL, base_version INTEGER NOT NULL,
              restored_from_version INTEGER, save_identity TEXT NOT NULL,
              host_id INTEGER REFERENCES authorized_hosts(id)
            );
            CREATE TABLE active_lock (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), session_hash TEXT NOT NULL UNIQUE,
              owner_user_id INTEGER NOT NULL REFERENCES users(id), token_id INTEGER REFERENCES api_tokens(id),
              owner_label TEXT NOT NULL, client_id TEXT NOT NULL, base_version INTEGER NOT NULL,
              created_at TEXT NOT NULL, last_heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL,
              host_id INTEGER REFERENCES authorized_hosts(id)
            );
            INSERT INTO users(username,role,active,display_name,slot)
              VALUES('admin','admin',1,'Alex','alex');
            """
        )
    config = dict(
        VALHEIM_CONFIG,
        SAVE_SYNC_STORAGE_PATH=str(storage),
        SAVE_SYNC_DB_PATH=str(db_path),
    )
    application = create_app(config)
    with application.extensions["save_sync_connect"]() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 5
        assert "last_ip" in {
            row[1] for row in db.execute("PRAGMA table_info(authorized_hosts)")
        }


def test_presence_is_public_and_never_exposes_ips(mclient):
    response = mclient.get(f"{API}/presence")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"locked": False}

    token, _ = create_host_token(mclient)
    acquired = lock_as(
        mclient,
        token,
        environ_overrides={"REMOTE_ADDR": "172.18.0.3"},
        headers={"X-Forwarded-For": "79.117.176.126"},
    )
    assert acquired.status_code == 201

    body = mclient.get(f"{API}/presence").get_json()
    assert body["locked"] is True
    assert body["owner"] == "Gamer"
    assert "since" in body
    assert "hostIp" not in body
    assert "lastIp" not in body
    assert "79.117" not in str(body)


def test_presence_never_writes_or_clears_expired_locks(mclient, mapp):
    token, _ = create_host_token(mclient)
    acquired = lock_as(mclient, token)
    assert acquired.status_code == 201
    session_id = acquired.get_json()["sessionId"]
    assert (
        mclient.post(
            f"{API}/unlock", headers=bearer(token), json={"sessionId": session_id}
        ).status_code
        == 200
    )
    # Reinsert an expired lock straight into the DB: presence must report it
    # as absent without deleting or touching it (read-only endpoint).
    with mapp.extensions["save_sync_connect"]() as db:
        db.execute(
            "INSERT INTO active_lock(singleton,session_hash,owner_user_id,"
            "owner_label,client_id,base_version,created_at,last_heartbeat_at,"
            "expires_at,host_id) VALUES(1,?,?,?,?,?,?,?,?,?)",
            (
                hashlib.sha256(b"expired-session").hexdigest(),
                3,
                "Gamer",
                "gamer-pc",
                0,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:01:00Z",
                1,
            ),
        )
    assert mclient.get(f"{API}/presence").get_json() == {"locked": False}
    with mapp.extensions["save_sync_connect"]() as db:
        row = db.execute(
            "SELECT owner_label FROM active_lock WHERE singleton=1"
        ).fetchone()
        assert row["owner_label"] == "Gamer"


def test_last_ip_recorded_behind_proxy_and_spoof_ignored(mclient, mapp):
    token, _ = create_host_token(mclient)
    acquired = lock_as(
        mclient,
        token,
        environ_overrides={"REMOTE_ADDR": "203.0.113.7"},
        headers={"X-Forwarded-For": "1.2.3.4"},
    )
    assert acquired.status_code == 201
    with mapp.extensions["save_sync_connect"]() as db:
        row = db.execute(
            "SELECT last_ip FROM authorized_hosts WHERE client_id='gamer-pc'"
        ).fetchone()
        # Untrusted direct peer: headers ignored, peer stored.
        assert row["last_ip"] == "203.0.113.7"


def test_status_hides_host_ip_from_players(mclient):
    token, _ = create_host_token(mclient)
    acquired = lock_as(mclient, token)
    assert acquired.status_code == 201

    player_status = mclient.get(f"{API}/status", headers=bearer(token)).get_json()
    assert player_status["locked"] is True
    assert "hostIp" not in player_status["lock"]

    admin_status = mclient.get(f"{API}/status", headers=auth("admin")).get_json()
    assert admin_status["lock"]["hostIp"] in (None, "127.0.0.1")

    forbidden = mclient.get(f"{API}/admin/hosts", headers=bearer(token))
    assert forbidden.status_code == 403


def test_client_config_authorization_and_privacy(mclient):
    _, host_id = create_host_token(mclient)
    url = f"{API}/admin/hosts/{host_id}/client-config"

    assert mclient.get(url).status_code == 401
    assert mclient.get(url, headers=auth("player")).status_code == 403

    player_token, _ = create_host_token(
        mclient, username="gamer2", client_id="gamer2-pc"
    )
    assert mclient.get(url, headers=bearer(player_token)).status_code == 403

    response = mclient.get(url, headers=auth("admin"))
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    body = response.get_json()
    assert body["ClientId"] == "gamer-pc"
    assert body["PlayerName"] == "Gamer"
    assert body["ApiBaseUrl"] == "https://sync.example.com/api/games/valheim"
    # Canonical base URL: a spoofed Host header must not leak into the file.
    spoofed = mclient.get(
        url,
        headers={**auth("admin"), "Host": "evil.example.com"},
    )
    assert spoofed.get_json()["ApiBaseUrl"] == "https://sync.example.com/api/games/valheim"
    lowered = str(body).lower()
    assert "pws_" not in lowered
    assert "secret" not in lowered

    assert mclient.get(f"{API}/admin/hosts/9999/client-config").status_code in (
        401,
        403,
        404,
    )
    assert (
        mclient.get(
            f"{API}/admin/hosts/9999/client-config", headers=auth("admin")
        ).status_code
        == 404
    )


def test_client_config_fails_closed_without_public_base_url(
    mclient, monkeypatch
):
    _, host_id = create_host_token(mclient)
    monkeypatch.delenv("SAVE_SYNC_PUBLIC_BASE_URL", raising=False)
    response = mclient.get(
        f"{API}/admin/hosts/{host_id}/client-config", headers=auth("admin")
    )
    assert response.status_code == 500
    assert response.get_json()["error"] == "server_misconfigured"


def test_client_config_unmanaged_game_returns_404(client):
    response = client.get(
        "/api/games/palworld/admin/hosts/1/client-config", headers=auth("admin")
    )
    assert response.status_code == 404


def test_invalid_proxy_cidrs_fail_at_startup(tmp_path):
    storage = tmp_path / "bad-cidrs"
    storage.mkdir()
    config = dict(
        VALHEIM_CONFIG,
        SAVE_SYNC_STORAGE_PATH=str(storage),
        SAVE_SYNC_DB_PATH=str(storage / "save-sync.sqlite3"),
        SAVE_SYNC_TRUSTED_PROXY_CIDRS="not-a-cidr",
    )
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_CIDRS"):
        create_app(config)


def test_extract_client_ip_unit():
    cidrs = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

    class FakeRequest:
        def __init__(self, peer, xff="", orig=True):
            self.environ = {"REMOTE_ADDR": peer}
            if orig:
                self.environ["werkzeug.proxy_fix.orig"] = {"REMOTE_ADDR": peer}
            self.headers = {"X-Forwarded-For": xff} if xff else {}

    # Trusted proxy peer + spoofed chain: rightmost untrusted wins.
    assert (
        extract_client_ip(
            FakeRequest("172.18.0.2", "1.2.3.4, 79.117.176.126"),
            trusted_cidrs=cidrs,
        )
        == "79.117.176.126"
    )
    # Untrusted direct peer: headers ignored entirely.
    assert (
        extract_client_ip(FakeRequest("203.0.113.7", "1.2.3.4"), trusted_cidrs=cidrs)
        == "203.0.113.7"
    )
    # No headers: peer itself.
    assert (
        extract_client_ip(FakeRequest("172.18.0.2"), trusted_cidrs=cidrs)
        == "172.18.0.2"
    )
    # Garbage peer: empty, never echoed back.
    assert extract_client_ip(FakeRequest("not-an-ip"), trusted_cidrs=cidrs) == ""
    # No ProxyFix orig either: falls back to REMOTE_ADDR.
    assert (
        extract_client_ip(
            FakeRequest("10.1.2.3", "9.9.9.9", orig=False), trusted_cidrs=cidrs
        )
        == "9.9.9.9"
    )
    # Default config trusts loopback only: a private peer is NOT a proxy.
    assert extract_client_ip(FakeRequest("172.18.0.2", "9.9.9.9")) == "172.18.0.2"
