import hashlib
import io
import sqlite3
import threading
from pathlib import Path

import pytest
from conftest import TOKENS, auth, zip_bytes

from save_sync import create_app
from save_sync.app import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
API = "/api/games/valheim"
WEB = "/games/valheim"
WORLD_UID = "2352155610"


@pytest.fixture
def app(tmp_path):
    storage = tmp_path / "valheim-storage"
    application = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_GAME_KEY": "valheim",
            "SAVE_SYNC_GAME_CONFIG_PATH": str(ROOT / "config/games/valheim.json"),
            "SAVE_SYNC_STORAGE_PATH": str(storage),
            "SAVE_SYNC_DB_PATH": str(storage / "save-sync.sqlite3"),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
            "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
            "SAVE_SYNC_MAX_UPLOAD_SIZE": 1024 * 1024,
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
            "SAVE_SYNC_LOCK_TTL_SECONDS": 300,
        }
    )
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
def client(app):
    return app.test_client()


def create_user(client, username, display_name, role="player"):
    response = client.post(
        f"{API}/admin/users",
        headers=auth("admin"),
        json={
            "username": username,
            "displayName": display_name,
            "slot": username,
            "role": role,
        },
    )
    assert response.status_code == 201
    return response.get_json()


def user_id(client, username):
    response = client.get(f"{API}/admin/users", headers=auth("admin"))
    assert response.status_code == 200
    return next(item["id"] for item in response.get_json()["users"] if item["username"] == username)


def create_host(client, target_user_id, client_id, name):
    response = client.post(
        f"{API}/admin/hosts",
        headers=auth("admin"),
        json={"userId": target_user_id, "clientId": client_id, "name": name},
    )
    assert response.status_code == 201
    return response.get_json()


def create_host_token(client, username, host_id, name):
    response = client.post(
        f"{API}/admin/tokens",
        headers=auth("admin"),
        json={"username": username, "hostId": host_id, "name": name},
    )
    assert response.status_code == 201
    return response.get_json()["token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_four_distinct_managed_computers_can_take_turns(client):
    create_user(client, "player3", "Host C")
    create_user(client, "player4", "Host D")
    identities = {
        "admin": (user_id(client, "admin"), "Host A", "alex-pc"),
        "player": (user_id(client, "player"), "Host B", "sofia-pc"),
        "player3": (user_id(client, "player3"), "Host C", "arnau-pc"),
        "player4": (user_id(client, "player4"), "Host D", "pc4"),
    }
    hosts = {}
    tokens = {}
    for username, (target_user_id, _, client_id) in identities.items():
        hosts[username] = create_host(
            client, target_user_id, client_id, f"{username} computer"
        )
        tokens[username] = create_host_token(
            client, username, hosts[username]["id"], f"{username}-sync"
        )

    for username, (_, display_name, client_id) in identities.items():
        acquired = client.post(
            f"{API}/lock",
            headers=bearer(tokens[username]),
            json={"owner": display_name, "clientId": client_id},
        )
        assert acquired.status_code == 201
        status = client.get(
            f"{API}/status", headers=auth("admin")
        ).get_json()
        assert status["lock"]["clientId"] == client_id
        assert status["lock"]["hostName"] == f"{username} computer"
        released = client.post(
            f"{API}/unlock",
            headers=bearer(tokens[username]),
            json={"sessionId": acquired.get_json()["sessionId"]},
        )
        assert released.status_code == 200

    listed = client.get(
        f"{API}/admin/hosts", headers=auth("admin")
    ).get_json()["hosts"]
    assert {item["clientId"] for item in listed} == {
        "alex-pc",
        "sofia-pc",
        "arnau-pc",
        "pc4",
    }


def test_bound_token_cannot_spoof_another_computer_or_administer(client):
    admin_id = user_id(client, "admin")
    first = create_host(client, admin_id, "alex-main", "Alex main")
    create_host(client, admin_id, "alex-laptop", "Alex laptop")
    token = create_host_token(client, "admin", first["id"], "alex-main-sync")

    spoofed = client.post(
        f"{API}/lock",
        headers=bearer(token),
        json={"owner": "Host A", "clientId": "alex-laptop"},
    )
    assert spoofed.status_code == 403
    assert spoofed.get_json()["error"] == "token_host_mismatch"

    admin_operation = client.post(
        f"{API}/admin/users",
        headers=bearer(token),
        json={
            "username": "intruder",
            "displayName": "Intruder",
            "slot": "intruder",
            "role": "admin",
        },
    )
    assert admin_operation.status_code == 403


def test_managed_valheim_requires_computer_bound_tokens(client):
    unbound = client.post(
        f"{API}/lock",
        headers=auth("player"),
        json={"owner": "Host B", "clientId": "unregistered-pc"},
    )
    assert unbound.status_code == 403
    assert unbound.get_json()["error"] == "host_token_required"

    token_without_host = client.post(
        f"{API}/admin/tokens",
        headers=auth("admin"),
        json={"username": "player", "name": "must-be-bound"},
    )
    assert token_without_host.status_code == 400
    assert token_without_host.get_json()["error"] == "invalid_request"


def test_token_revoked_after_auth_cannot_acquire_managed_lock(app, client, monkeypatch):
    player_id = user_id(client, "player")
    host = create_host(client, player_id, "race-lock-pc", "Race lock PC")
    token = create_host_token(client, "player", host["id"], "race-lock-token")

    import secrets

    original_token_urlsafe = secrets.token_urlsafe
    authenticated = threading.Event()
    continue_request = threading.Event()

    def pause_before_transaction(length):
        authenticated.set()
        assert continue_request.wait(5)
        return original_token_urlsafe(length)

    monkeypatch.setattr("save_sync.app.secrets.token_urlsafe", pause_before_transaction)
    result = {}

    def acquire_after_auth():
        response = app.test_client().post(
            f"{API}/lock",
            headers=bearer(token),
            json={"owner": "Host B", "clientId": "race-lock-pc"},
        )
        result["status"] = response.status_code
        result["body"] = response.get_json()

    thread = threading.Thread(target=acquire_after_auth)
    thread.start()
    assert authenticated.wait(5)
    with app.extensions["save_sync_connect"]() as db:
        db.execute(
            "UPDATE api_tokens SET revoked_at=datetime('now') WHERE token_hash=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
    continue_request.set()
    thread.join(5)
    assert not thread.is_alive()
    assert result["status"] == 403
    assert result["body"]["error"] == "access_revoked"
    with app.extensions["save_sync_connect"]() as db:
        assert db.execute("SELECT COUNT(*) FROM active_lock").fetchone()[0] == 0


def test_token_revoked_after_auth_cannot_extend_managed_heartbeat(
    app, client, monkeypatch
):
    player_id = user_id(client, "player")
    host = create_host(client, player_id, "race-heartbeat-pc", "Race heartbeat PC")
    token = create_host_token(client, "player", host["id"], "race-heartbeat-token")
    acquired = client.post(
        f"{API}/lock",
        headers=bearer(token),
        json={"owner": "Host B", "clientId": "race-heartbeat-pc"},
    )
    assert acquired.status_code == 201
    session_id = acquired.get_json()["sessionId"]
    original_expiry = acquired.get_json()["expiresAt"]

    import save_sync.app as app_module

    original_utcnow = app_module.utcnow
    calls = 0
    authenticated = threading.Event()
    continue_request = threading.Event()

    def pause_after_auth():
        nonlocal calls
        calls += 1
        if calls == 2:
            authenticated.set()
            assert continue_request.wait(5)
        return original_utcnow()

    monkeypatch.setattr("save_sync.app.utcnow", pause_after_auth)
    result = {}

    def heartbeat_after_auth():
        response = app.test_client().post(
            f"{API}/heartbeat",
            headers=bearer(token),
            json={"sessionId": session_id},
        )
        result["status"] = response.status_code
        result["body"] = response.get_json()

    thread = threading.Thread(target=heartbeat_after_auth)
    thread.start()
    assert authenticated.wait(5)
    with app.extensions["save_sync_connect"]() as db:
        db.execute(
            "UPDATE api_tokens SET revoked_at=datetime('now') WHERE token_hash=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
    continue_request.set()
    thread.join(5)
    assert not thread.is_alive()
    assert result["status"] == 403
    assert result["body"]["error"] == "access_revoked"
    with app.extensions["save_sync_connect"]() as db:
        lock = db.execute("SELECT expires_at FROM active_lock WHERE singleton=1").fetchone()
        assert lock is not None
        assert lock["expires_at"] == original_expiry


def test_disabling_active_host_stops_heartbeat_but_preserves_lock(client):
    player_id = user_id(client, "player")
    host = create_host(client, player_id, "sofia-pc", "Sofia computer")
    token = create_host_token(client, "player", host["id"], "sofia-sync")
    acquired = client.post(
        f"{API}/lock",
        headers=bearer(token),
        json={"owner": "Host B", "clientId": "sofia-pc"},
    )
    assert acquired.status_code == 201

    disabled = client.patch(
        f"{API}/admin/hosts/{host['id']}",
        headers=auth("admin"),
        json={"active": False},
    )
    assert disabled.status_code == 200
    heartbeat = client.post(
        f"{API}/heartbeat",
        headers=bearer(token),
        json={"sessionId": acquired.get_json()["sessionId"]},
    )
    assert heartbeat.status_code == 403
    assert heartbeat.get_json()["error"] == "host_disabled"
    status = client.get(f"{API}/status", headers=auth("admin")).get_json()
    assert status["locked"] is True
    assert status["lock"]["clientId"] == "sofia-pc"


def test_another_token_for_same_user_cannot_take_over_active_session(client):
    player_id = user_id(client, "player")
    first = create_host(client, player_id, "sofia-main", "Sofia main")
    second = create_host(client, player_id, "sofia-laptop", "Sofia laptop")
    first_token = create_host_token(client, "player", first["id"], "main-token")
    second_token = create_host_token(client, "player", second["id"], "laptop-token")
    acquired = client.post(
        f"{API}/lock",
        headers=bearer(first_token),
        json={"owner": "Host B", "clientId": "sofia-main"},
    ).get_json()

    hijack = client.post(
        f"{API}/heartbeat",
        headers=bearer(second_token),
        json={"sessionId": acquired["sessionId"]},
    )
    assert hijack.status_code == 403
    assert hijack.get_json()["error"] == "token_host_mismatch"


def test_publication_records_computer_provenance_and_audit(client):
    player_id = user_id(client, "player")
    host = create_host(client, player_id, "sofia-pc", "Sofia computer")
    token = create_host_token(client, "player", host["id"], "sofia-sync")
    acquired = client.post(
        f"{API}/lock",
        headers=bearer(token),
        json={"owner": "Host B", "clientId": "sofia-pc"},
    ).get_json()
    payload = zip_bytes(b"managed-host-save")
    response = client.post(
        f"{API}/upload",
        headers=bearer(token),
        data={
            "file": (io.BytesIO(payload), "save.zip"),
            "sessionId": acquired["sessionId"],
            "baseVersion": "0",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "worldUid": WORLD_UID,
        },
    )
    assert response.status_code == 201

    status = client.get(f"{API}/status", headers=auth("admin")).get_json()
    assert status["updatedClientId"] == "sofia-pc"
    assert status["updatedHostName"] == "Sofia computer"
    history = client.get(
        f"{API}/history", headers=auth("admin")
    ).get_json()["versions"]
    assert history[0]["clientId"] == "sofia-pc"
    assert history[0]["hostName"] == "Sofia computer"
    hosts = client.get(
        f"{API}/admin/hosts", headers=auth("admin")
    ).get_json()["hosts"]
    published_host = next(item for item in hosts if item["id"] == host["id"])
    assert published_host["lastPublishedAt"] is not None
    audit = client.get(
        f"{API}/admin/audit?limit=50", headers=auth("admin")
    ).get_json()["events"]
    started = next(item for item in audit if item["event"] == "upload_started")
    completed = next(item for item in audit if item["event"] == "upload_completed")
    assert started["client_id"] == "sofia-pc"
    assert completed["client_id"] == "sofia-pc"


def test_last_active_admin_cannot_be_disabled_or_demoted(client):
    admin_id = user_id(client, "admin")
    disabled = client.patch(
        f"{API}/admin/users/{admin_id}",
        headers=auth("admin"),
        json={"active": False},
    )
    assert disabled.status_code == 409
    assert disabled.get_json()["error"] == "last_admin"
    demoted = client.patch(
        f"{API}/admin/users/{admin_id}",
        headers=auth("admin"),
        json={"role": "player"},
    )
    assert demoted.status_code == 409
    assert demoted.get_json()["error"] == "last_admin"


def test_disabling_user_revokes_web_access(client):
    created = create_user(client, "friend", "Friend")
    web = {
        "X-authentik-username": "friend",
        "X-Save-Sync-Proxy-Secret": "proxy-test-secret",
    }
    assert client.get(WEB, headers=web).status_code == 200
    assert (
        client.patch(
            f"{API}/admin/users/{created['id']}",
            headers=auth("admin"),
            json={"active": False},
        ).status_code
        == 200
    )
    assert client.get(WEB, headers=web).status_code == 403


def test_web_admin_can_create_user_and_host_with_csrf(client):
    # Match csrf_value without importing a private application closure.
    import hmac

    token = hmac.new(
        b"csrf-test-secret", b"valheim:admin", hashlib.sha256
    ).hexdigest()
    web = {
        "X-authentik-username": "admin",
        "X-Save-Sync-Proxy-Secret": "proxy-test-secret",
        "X-CSRF-Token": token,
    }
    created_user = client.post(
        f"{WEB}/api/admin/users",
        headers=web,
        json={
            "username": "webplayer",
            "displayName": "Web Player",
            "slot": "webplayer",
            "role": "player",
        },
    )
    assert created_user.status_code == 201
    created_host = client.post(
        f"{WEB}/api/admin/hosts",
        headers=web,
        json={
            "userId": created_user.get_json()["id"],
            "clientId": "web-pc",
            "name": "Web PC",
        },
    )
    assert created_host.status_code == 201
    panel = client.get(
        WEB,
        headers={
            "X-authentik-username": "admin",
            "X-Save-Sync-Proxy-Secret": "proxy-test-secret",
        },
    ).get_data(as_text=True)
    assert 'id="accessCard"' in panel


def test_palworld_keeps_legacy_unmanaged_host_flow(tmp_path):
    storage = tmp_path / "palworld-storage"
    application = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_STORAGE_PATH": str(storage),
            "SAVE_SYNC_DB_PATH": str(storage / "save-sync.sqlite3"),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
            "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
        }
    )
    token = TOKENS["admin"]
    with application.extensions["save_sync_connect"]() as db:
        admin = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        db.execute(
            "INSERT INTO api_tokens(user_id,name,token_hash,created_at) "
            "VALUES(?,?,?,datetime('now'))",
            (admin, "legacy-admin", hashlib.sha256(token.encode()).hexdigest()),
        )
    palworld = application.test_client()
    headers = bearer(token)

    rules = {rule.rule for rule in application.url_map.iter_rules()}
    for path in (
        "/api/games/palworld/admin/users",
        "/games/palworld/api/admin/users",
        "/api/palworld/admin/users",
        "/palworld/api/admin/users",
        "/api/games/palworld/admin/hosts",
        "/games/palworld/api/admin/hosts",
        "/api/palworld/admin/hosts",
        "/palworld/api/admin/hosts",
    ):
        assert path not in rules
        assert palworld.get(path).status_code == 404
    assert palworld.get("/api/games/palworld/admin/users", headers=headers).status_code == 404
    assert palworld.get("/api/games/palworld/admin/hosts", headers=headers).status_code == 404

    legacy_tokens = palworld.get(
        "/api/games/palworld/admin/tokens", headers=headers
    ).get_json()["tokens"]
    assert set(legacy_tokens[0]) == {
        "id",
        "name",
        "created_at",
        "last_used_at",
        "revoked_at",
        "username",
    }
    created_legacy_token = palworld.post(
        "/api/games/palworld/admin/tokens",
        headers=headers,
        json={"username": "admin", "name": "x" * 101},
    )
    assert created_legacy_token.status_code == 201
    assert set(created_legacy_token.get_json()) == {"id", "token", "username", "name"}

    acquired = palworld.post(
        "/api/games/palworld/lock",
        headers=headers,
        json={"owner": "Host A", "clientId": "legacy-pc"},
    )
    assert acquired.status_code == 201
    status = palworld.get("/api/games/palworld/status", headers=headers).get_json()
    assert status["locked"] is True
    assert "clientId" not in status["lock"]
    assert "hostName" not in status["lock"]

    panel = palworld.get(
        "/games/palworld",
        headers={
            "X-authentik-username": "admin",
            "X-Palworld-Proxy-Secret": "proxy-test-secret",
        },
    )
    assert panel.status_code == 200
    text = panel.get_data(as_text=True)
    assert "Access & computers" not in text
    assert "managedHosts" not in text
    assert "body{max-width:980px;margin:3rem auto" in text
    assert 'id="tokenName"' in text
    assert 'id="accessCard"' not in text


def test_schema_three_migrates_managed_host_columns(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    db_path = storage / "save-sync.sqlite3"
    legacy_token = "pws_schema3_legacy_token"
    legacy_session = "schema3-active-session"
    legacy_expiry = "2099-01-01T00:00:00Z"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            PRAGMA user_version=3;
            CREATE TABLE users (
              id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
              role TEXT NOT NULL CHECK(role IN ('admin','player')),
              active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE api_tokens (
              id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
              name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT
            );
            CREATE TABLE versions (
              version INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL,
              size INTEGER NOT NULL, updated_by INTEGER NOT NULL REFERENCES users(id),
              updated_at TEXT NOT NULL, base_version INTEGER NOT NULL,
              restored_from_version INTEGER, save_identity TEXT NOT NULL
            );
            CREATE TABLE active_lock (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), session_hash TEXT NOT NULL UNIQUE,
              owner_user_id INTEGER NOT NULL REFERENCES users(id), token_id INTEGER REFERENCES api_tokens(id),
              owner_label TEXT NOT NULL, client_id TEXT NOT NULL, base_version INTEGER NOT NULL,
              created_at TEXT NOT NULL, last_heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL
            );
            INSERT INTO users(username,role,active) VALUES('admin','admin',1);
            """
        )
        db.execute(
            "INSERT INTO api_tokens(id,user_id,name,token_hash,created_at) VALUES(1,1,?,?,?)",
            (
                "legacy",
                hashlib.sha256(legacy_token.encode()).hexdigest(),
                "2026-09-10T00:00:00Z",
            ),
        )
        db.execute(
            "INSERT INTO active_lock(singleton,session_hash,owner_user_id,token_id,owner_label,"
            "client_id,base_version,created_at,last_heartbeat_at,expires_at) "
            "VALUES(1,?,?,?,?,?,?,?,?,?)",
            (
                hashlib.sha256(legacy_session.encode()).hexdigest(),
                1,
                1,
                "Alex",
                "legacy-pc",
                0,
                "2026-09-10T00:00:00Z",
                "2026-09-10T00:00:00Z",
                legacy_expiry,
            ),
        )
    application = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_GAME_KEY": "valheim",
            "SAVE_SYNC_GAME_CONFIG_PATH": str(ROOT / "config/games/valheim.json"),
            "SAVE_SYNC_STORAGE_PATH": str(storage),
            "SAVE_SYNC_DB_PATH": str(db_path),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
            "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
            "SAVE_SYNC_WEB_USERS": "admin:admin",
            "SAVE_SYNC_USER_IDENTITIES_JSON": (
                '{"admin":{"displayName":"Alex","slot":"alex"}}'
            ),
        }
    )
    with application.extensions["save_sync_connect"]() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert {row[1] for row in db.execute("PRAGMA table_info(users)")} >= {
            "display_name",
            "slot",
        }
        assert "host_id" in {
            row[1] for row in db.execute("PRAGMA table_info(api_tokens)")
        }
        assert "host_id" in {
            row[1] for row in db.execute("PRAGMA table_info(active_lock)")
        }
        assert "host_id" in {
            row[1] for row in db.execute("PRAGMA table_info(versions)")
        }
        profile = db.execute(
            "SELECT display_name,slot FROM users WHERE username='admin'"
        ).fetchone()
        assert tuple(profile) == ("Alex", "alex")
        migrated_lock = db.execute(
            "SELECT host_id,expires_at FROM active_lock WHERE singleton=1"
        ).fetchone()
        assert migrated_lock["host_id"] is None
        assert migrated_lock["expires_at"] == legacy_expiry

    migrated_client = application.test_client()
    heartbeat = migrated_client.post(
        "/api/games/valheim/heartbeat",
        headers=bearer(legacy_token),
        json={"sessionId": legacy_session},
    )
    assert heartbeat.status_code == 403
    assert heartbeat.get_json()["error"] == "host_token_required"

    payload = zip_bytes(b"legacy-schema-three")
    upload = migrated_client.post(
        "/api/games/valheim/upload",
        headers=bearer(legacy_token),
        data={
            "file": (io.BytesIO(payload), "save.zip"),
            "sessionId": legacy_session,
            "baseVersion": "0",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "worldUid": WORLD_UID,
        },
    )
    assert upload.status_code == 409
    assert upload.get_json()["error"] == "managed_session_required"
    with application.extensions["save_sync_connect"]() as db:
        assert db.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 0
        lock = db.execute(
            "SELECT host_id,expires_at FROM active_lock WHERE singleton=1"
        ).fetchone()
        assert lock["host_id"] is None
        assert lock["expires_at"] == legacy_expiry


def test_valheim_panel_and_managed_host_routes_use_same_access_model(tmp_path):
    storage = tmp_path / "valheim-storage"
    application = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_GAME_KEY": "valheim",
            "SAVE_SYNC_GAME_CONFIG_PATH": str(ROOT / "config/games/valheim.json"),
            "SAVE_SYNC_STORAGE_PATH": str(storage),
            "SAVE_SYNC_DB_PATH": str(storage / "save-sync.sqlite3"),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
            "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
            "SAVE_SYNC_WEB_USERS": "admin:admin",
            "SAVE_SYNC_USER_IDENTITIES_JSON": (
                '{"admin":{"displayName":"Alex","slot":"alex"}}'
            ),
        }
    )
    legacy_admin_token = "pws_valheim_admin_test"
    with application.extensions["save_sync_connect"]() as db:
        admin = db.execute(
            "SELECT id FROM users WHERE username='admin'"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO api_tokens(user_id,name,token_hash,created_at) VALUES(?,?,?,datetime('now'))",
            (admin, "bootstrap", hashlib.sha256(legacy_admin_token.encode()).hexdigest()),
        )
    client = application.test_client()
    admin_headers = {"Authorization": f"Bearer {legacy_admin_token}"}
    host = client.post(
        "/api/games/valheim/admin/hosts",
        headers=admin_headers,
        json={"userId": admin, "clientId": "alex-valheim-pc", "name": "Alex PC"},
    )
    assert host.status_code == 201
    created_token = client.post(
        "/api/games/valheim/admin/tokens",
        headers=admin_headers,
        json={
            "username": "admin",
            "hostId": host.get_json()["id"],
            "name": "valheim-sync",
        },
    )
    assert created_token.status_code == 201
    acquired = client.post(
        "/api/games/valheim/lock",
        headers=bearer(created_token.get_json()["token"]),
        json={"owner": "Alex", "clientId": "alex-valheim-pc"},
    )
    assert acquired.status_code == 201
    panel = client.get(
        "/games/valheim",
        headers={
            "X-authentik-username": "admin",
            "X-Save-Sync-Proxy-Secret": "proxy-test-secret",
        },
    )
    assert panel.status_code == 200
    text = panel.get_data(as_text=True)
    assert "Valheim synchronization" in text
    assert 'id="accessCard"' in text
