import fcntl
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 4

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL CHECK(role IN ('admin','player')), active INTEGER NOT NULL DEFAULT 1,
 display_name TEXT, slot TEXT
);
CREATE TABLE IF NOT EXISTS authorized_hosts (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), client_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL, last_seen_at TEXT, last_published_at TEXT
);
CREATE TABLE IF NOT EXISTS api_tokens (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT, host_id INTEGER REFERENCES authorized_hosts(id)
);
CREATE TABLE IF NOT EXISTS versions (
 version INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
 updated_by INTEGER NOT NULL REFERENCES users(id), updated_at TEXT NOT NULL, base_version INTEGER NOT NULL,
 restored_from_version INTEGER, save_identity TEXT NOT NULL CHECK(length(save_identity) BETWEEN 1 AND 256),
 host_id INTEGER REFERENCES authorized_hosts(id)
);
CREATE TABLE IF NOT EXISTS current_save (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL REFERENCES versions(version)
);
CREATE TABLE IF NOT EXISTS active_lock (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), session_hash TEXT NOT NULL UNIQUE,
 owner_user_id INTEGER NOT NULL REFERENCES users(id), token_id INTEGER REFERENCES api_tokens(id), owner_label TEXT NOT NULL, client_id TEXT NOT NULL,
 base_version INTEGER NOT NULL, created_at TEXT NOT NULL, last_heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 host_id INTEGER REFERENCES authorized_hosts(id)
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, event TEXT NOT NULL, user_id INTEGER, at TEXT NOT NULL, success INTEGER NOT NULL,
 client_id TEXT, details TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS rate_limits (
  identity TEXT NOT NULL, window INTEGER NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(identity, window)
);
CREATE TABLE IF NOT EXISTS pending_backups (
  version INTEGER PRIMARY KEY REFERENCES versions(version),
  started_at TEXT NOT NULL
);
"""


def connect_database(db_path):
    db = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    return db


@contextmanager
def schema_lock(db_path):
    lock_path = Path(str(db_path) + ".migration.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.fchmod(descriptor, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _iso_utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def bootstrap_database(
    *,
    db_path,
    app_config,
    identities,
    managed_hosts,
    normalize_identity_value,
):
    with schema_lock(db_path), connect_database(db_path) as db:
        database_version = db.execute("PRAGMA user_version").fetchone()[0]
        if database_version > SCHEMA_VERSION:
            raise RuntimeError(
                f"The database uses schema {database_version}, but this version "
                f"supports only up to {SCHEMA_VERSION}; no downgrade will be performed"
            )
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        try:
            user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
            if "display_name" not in user_columns:
                db.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
            if "slot" not in user_columns:
                db.execute("ALTER TABLE users ADD COLUMN slot TEXT")

            token_columns = {row[1] for row in db.execute("PRAGMA table_info(api_tokens)")}
            if "host_id" not in token_columns:
                db.execute(
                    "ALTER TABLE api_tokens ADD COLUMN host_id INTEGER REFERENCES authorized_hosts(id)"
                )

            lock_columns = {row[1] for row in db.execute("PRAGMA table_info(active_lock)")}
            if "token_id" not in lock_columns:
                db.execute(
                    "ALTER TABLE active_lock ADD COLUMN token_id INTEGER REFERENCES api_tokens(id)"
                )
            if "host_id" not in lock_columns:
                db.execute(
                    "ALTER TABLE active_lock ADD COLUMN host_id INTEGER REFERENCES authorized_hosts(id)"
                )

            version_columns = {row[1] for row in db.execute("PRAGMA table_info(versions)")}
            if "world_guid" in version_columns:
                raise RuntimeError(
                    "The Palworld v1 database cannot be reused directly; "
                    "deploy Save Sync v2 with separate storage"
                )
            if "save_identity" not in version_columns:
                db.execute("ALTER TABLE versions ADD COLUMN save_identity TEXT")
            if "host_id" not in version_columns:
                db.execute(
                    "ALTER TABLE versions ADD COLUMN host_id INTEGER REFERENCES authorized_hosts(id)"
                )

            for row in db.execute("SELECT id,username,display_name,slot FROM users"):
                profile = identities.get(
                    row["username"].casefold(),
                    {"displayName": row["username"], "slot": row["username"].casefold()},
                )
                db.execute(
                    "UPDATE users SET display_name=COALESCE(NULLIF(display_name,''),?), "
                    "slot=COALESCE(NULLIF(slot,''),?) WHERE id=?",
                    (profile["displayName"], profile["slot"], row["id"]),
                )

            for trigger_sql in (
                """
                CREATE TRIGGER IF NOT EXISTS versions_save_identity_insert
                BEFORE INSERT ON versions
                WHEN NEW.save_identity IS NULL
                     OR length(NEW.save_identity) NOT BETWEEN 1 AND 256
                BEGIN SELECT RAISE(ABORT, 'invalid_save_identity'); END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS versions_save_identity_update
                BEFORE UPDATE OF save_identity ON versions
                WHEN NEW.save_identity IS NULL
                     OR length(NEW.save_identity) NOT BETWEEN 1 AND 256
                BEGIN SELECT RAISE(ABORT, 'invalid_save_identity'); END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS current_save_save_identity_insert
                BEFORE INSERT ON current_save
                WHEN (SELECT save_identity FROM versions WHERE version=NEW.version) IS NULL
                BEGIN SELECT RAISE(ABORT, 'missing_save_identity'); END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS current_save_save_identity_update
                BEFORE UPDATE OF version ON current_save
                WHEN (SELECT save_identity FROM versions WHERE version=NEW.version) IS NULL
                BEGIN SELECT RAISE(ABORT, 'missing_save_identity'); END
                """,
            ):
                db.execute(trigger_sql)
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            db.commit()
        except Exception:
            db.rollback()
            raise

        invalid_identity = next(
            (
                row
                for row in db.execute(
                    "SELECT version,save_identity FROM versions ORDER BY version"
                )
                if normalize_identity_value(row["save_identity"]) is None
                or normalize_identity_value(row["save_identity"]) != row["save_identity"]
            ),
            None,
        )
        if invalid_identity:
            raise RuntimeError(
                "The existing database contains a version without a valid save_identity; "
                "startup is rejected to avoid mixing different saves"
            )

        for item in app_config["SAVE_SYNC_WEB_USERS"].split(","):
            username, role = item.strip().split(":", 1)
            profile = identities.get(
                username.casefold(),
                {"displayName": username, "slot": username.casefold()},
            )
            if managed_hosts:
                existing_user = db.execute(
                    "SELECT id FROM users WHERE username=? COLLATE NOCASE", (username,)
                ).fetchone()
                if not existing_user:
                    db.execute(
                        "INSERT INTO users(username,role,display_name,slot) VALUES(?,?,?,?)",
                        (username, role, profile["displayName"], profile["slot"]),
                    )
                db.execute(
                    "UPDATE users SET display_name=COALESCE(NULLIF(display_name,''),?), "
                    "slot=COALESCE(NULLIF(slot,''),?) WHERE username=? COLLATE NOCASE",
                    (profile["displayName"], profile["slot"], username),
                )
            else:
                db.execute(
                    "INSERT INTO users(username,role,display_name,slot) VALUES(?,?,?,?) "
                    "ON CONFLICT(username) DO UPDATE SET role=excluded.role,"
                    "display_name=excluded.display_name,slot=excluded.slot",
                    (username, role, profile["displayName"], profile["slot"]),
                )

        bootstrap = os.environ.get("SAVE_SYNC_BOOTSTRAP_TOKENS_JSON")
        if bootstrap:
            for item in json.loads(bootstrap):
                user = db.execute(
                    "SELECT id FROM users WHERE username=?", (item["username"],)
                ).fetchone()
                if user:
                    db.execute(
                        "INSERT OR IGNORE INTO api_tokens(user_id,name,token_hash,created_at) VALUES(?,?,?,?)",
                        (user["id"], item["name"], _digest(item["token"]), _iso_utcnow()),
                    )
