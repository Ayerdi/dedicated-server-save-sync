import fcntl
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shlex
import signal
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path, PurePosixPath

from flask import Flask, Response, g, jsonify, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

GAME_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SCHEMA_VERSION = 3


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def error(code, message, status, details=None):
    return jsonify(error=code, message=message, details=details or {}), status


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL CHECK(role IN ('admin','player')), active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS api_tokens (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS versions (
 version INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
 updated_by INTEGER NOT NULL REFERENCES users(id), updated_at TEXT NOT NULL, base_version INTEGER NOT NULL,
 restored_from_version INTEGER, save_identity TEXT NOT NULL CHECK(length(save_identity) BETWEEN 1 AND 256)
);
CREATE TABLE IF NOT EXISTS current_save (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL REFERENCES versions(version)
);
CREATE TABLE IF NOT EXISTS active_lock (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), session_hash TEXT NOT NULL UNIQUE,
 owner_user_id INTEGER NOT NULL REFERENCES users(id), token_id INTEGER REFERENCES api_tokens(id), owner_label TEXT NOT NULL, client_id TEXT NOT NULL,
 base_version INTEGER NOT NULL, created_at TEXT NOT NULL, last_heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL
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


DEFAULTS = {
    "SAVE_SYNC_STORAGE_PATH": "/data/save-sync",
    "SAVE_SYNC_DB_PATH": "/data/save-sync/save-sync.sqlite3",
    "SAVE_SYNC_GAME_KEY": "palworld",
    "SAVE_SYNC_GAME_CONFIG_PATH": "",
    "SAVE_SYNC_MAX_UPLOAD_SIZE": 1073741824,
    "SAVE_SYNC_LOCK_TTL_SECONDS": 300,
    "SAVE_SYNC_HEARTBEAT_INTERVAL_SECONDS": 60,
    "SAVE_SYNC_MAX_ZIP_ENTRIES": 20000,
    "SAVE_SYNC_MAX_UNCOMPRESSED_SIZE": 10737418240,
    "SAVE_SYNC_MAX_COMPRESSION_RATIO": 200,
    "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 120,
    "SAVE_SYNC_WEB_USERS": "admin:admin,player:player",
    "SAVE_SYNC_USER_IDENTITIES_JSON": (
        '{"admin":{"displayName":"Host A","slot":"host-a"},'
        '"player":{"displayName":"Host B","slot":"host-b"}}'
    ),
    "SAVE_SYNC_REQUIRE_HTTPS": True,
    "SAVE_SYNC_PROXY_SECRET": "",
    "SAVE_SYNC_RETENTION_PER_SLOT": 1,
    "SAVE_SYNC_POST_PUBLISH_COMMAND": "",
    "SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS": 1800,
}


DEFAULT_GAME = {
    "key": "palworld",
    "displayName": "Palworld",
    "identityField": "worldGuid",
    "identityLabel": "World GUID",
    "identityPattern": r"^[A-F0-9]{32}$",
    "identityNormalization": "uppercase",
    "legacyPalworldRoutes": True,
}


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(DEFAULTS)
    for key, default in DEFAULTS.items():
        if key not in os.environ:
            continue
        raw = os.environ[key]
        if isinstance(default, bool):
            app.config[key] = raw.lower() in {"1", "true", "yes", "on"}
        elif isinstance(default, int):
            app.config[key] = int(raw)
        else:
            app.config[key] = raw
    app.config.update(config or {})
    if int(app.config["SAVE_SYNC_RETENTION_PER_SLOT"]) < 1:
        raise RuntimeError("SAVE_SYNC_RETENTION_PER_SLOT debe ser >= 1")
    if int(app.config["SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS"]) < 1:
        raise RuntimeError("SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS debe ser >= 1")
    game = dict(DEFAULT_GAME)
    game_config_path = str(app.config.get("SAVE_SYNC_GAME_CONFIG_PATH", "")).strip()
    if game_config_path:
        try:
            loaded_game = json.loads(Path(game_config_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("No se pudo cargar la configuración del juego") from exc
        if not isinstance(loaded_game, dict):
            raise RuntimeError("La configuración del juego debe ser un objeto JSON")
        game.update(loaded_game)
    game_key = str(game.get("key", "")).strip().lower()
    expected_game_key = str(app.config["SAVE_SYNC_GAME_KEY"]).strip().lower()
    display_game = str(game.get("displayName", "")).strip()
    identity_field = str(game.get("identityField", "")).strip()
    identity_label = str(game.get("identityLabel", "")).strip()
    normalization = str(game.get("identityNormalization", "none")).strip().lower()
    if not GAME_KEY_RE.fullmatch(game_key):
        raise RuntimeError("game.key debe usar minúsculas, números y guiones")
    if expected_game_key != game_key:
        raise RuntimeError("SAVE_SYNC_GAME_KEY no coincide con game.key")
    if not display_game or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", identity_field):
        raise RuntimeError("displayName o identityField no son válidos")
    if not identity_label or normalization not in {"none", "uppercase", "lowercase"}:
        raise RuntimeError("identityLabel o identityNormalization no son válidos")
    try:
        identity_re = re.compile(str(game.get("identityPattern", "")))
    except re.error as exc:
        raise RuntimeError("identityPattern no es una expresión regular válida") from exc
    if not game.get("identityPattern"):
        raise RuntimeError("identityPattern es obligatorio")
    legacy_palworld = bool(game.get("legacyPalworldRoutes", False))

    def normalize_identity_value(value):
        raw = str(value or "").strip()
        if normalization == "uppercase":
            raw = raw.upper()
        elif normalization == "lowercase":
            raw = raw.lower()
        if not raw or len(raw) > 256 or not identity_re.fullmatch(raw):
            return None
        return raw

    app.extensions["save_sync_game"] = {
        **game,
        "key": game_key,
        "displayName": display_game,
        "identityField": identity_field,
        "identityLabel": identity_label,
    }
    try:
        raw_identities = json.loads(app.config["SAVE_SYNC_USER_IDENTITIES_JSON"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("SAVE_SYNC_USER_IDENTITIES_JSON no es JSON válido") from exc
    if not isinstance(raw_identities, dict):
        raise RuntimeError("SAVE_SYNC_USER_IDENTITIES_JSON debe ser un objeto JSON")  # noqa: TRY004
    identities = {}
    for username, profile in raw_identities.items():
        if not isinstance(profile, dict):
            raise RuntimeError(f"Perfil de identidad inválido para {username}")  # noqa: TRY004
        display = str(profile.get("displayName", "")).strip()
        slot = str(profile.get("slot", "")).strip()
        if not username.strip() or not display or not slot:
            raise RuntimeError(
                "Cada identidad necesita username, displayName y slot no vacíos"
            )
        identities[username.casefold()] = {"displayName": display, "slot": slot}
    if not app.config.get("TESTING"):
        for required_secret in ("SAVE_SYNC_PROXY_SECRET", "SAVE_SYNC_CSRF_SECRET"):
            value = str(
                app.config.get(required_secret) or os.environ.get(required_secret, "")
            )
            if len(value) < 32 or value.startswith("REEMPLAZAR"):
                raise RuntimeError(
                    f"{required_secret} debe configurarse con al menos 32 caracteres aleatorios"
                )
    app.config["MAX_CONTENT_LENGTH"] = (
        int(app.config["SAVE_SYNC_MAX_UPLOAD_SIZE"]) + 1024 * 1024
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    storage = Path(app.config["SAVE_SYNC_STORAGE_PATH"]).resolve()
    (storage / "backups").mkdir(parents=True, exist_ok=True)
    (storage / "temporary").mkdir(parents=True, exist_ok=True)
    Path(app.config["SAVE_SYNC_DB_PATH"]).parent.mkdir(parents=True, exist_ok=True)

    def connect():
        db = sqlite3.connect(
            app.config["SAVE_SYNC_DB_PATH"], timeout=30, isolation_level=None
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @contextmanager
    def schema_lock():
        lock_path = Path(str(app.config["SAVE_SYNC_DB_PATH"]) + ".migration.lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    app.extensions["save_sync_connect"] = connect
    # El lock de fichero abarca todo el bootstrap porque PRAGMA
    # journal_mode=WAL puede fallar antes de que BEGIN IMMEDIATE llegue a
    # serializar la migración. El almacenamiento soportado es Linux local.
    with schema_lock(), connect() as db:
        database_version = db.execute("PRAGMA user_version").fetchone()[0]
        if database_version > SCHEMA_VERSION:
            raise RuntimeError(
                f"La base usa el esquema {database_version}, pero esta versión "
                f"solo admite hasta {SCHEMA_VERSION}; no se realizará downgrade"
            )
        db.executescript(SCHEMA)
        # La migración se serializa para que dos workers que arranquen a la vez
        # no intenten añadir la misma columna. Los triggers mantienen también
        # la restricción estricta en bases antiguas donde ALTER TABLE solo
        # permite añadir una columna inicialmente nullable.
        db.execute("BEGIN IMMEDIATE")
        try:
            lock_columns = {
                row[1] for row in db.execute("PRAGMA table_info(active_lock)")
            }
            if "token_id" not in lock_columns:
                db.execute(
                    "ALTER TABLE active_lock ADD COLUMN token_id INTEGER REFERENCES api_tokens(id)"
                )
            version_columns = {
                row[1] for row in db.execute("PRAGMA table_info(versions)")
            }
            if "world_guid" in version_columns:
                raise RuntimeError(
                    "La base Palworld v1 no puede reutilizarse directamente; "
                    "despliega Save Sync v2 con almacenamiento separado"
                )
            if "save_identity" not in version_columns:
                db.execute("ALTER TABLE versions ADD COLUMN save_identity TEXT")
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
                or normalize_identity_value(row["save_identity"])
                != row["save_identity"]
            ),
            None,
        )
        if invalid_identity:
            raise RuntimeError(
                "La base existente contiene una versión sin save_identity válido; "
                "se rechaza el arranque para evitar mezclar partidas"
            )
        for item in app.config["SAVE_SYNC_WEB_USERS"].split(","):
            username, role = item.strip().split(":", 1)
            db.execute(
                "INSERT INTO users(username,role) VALUES(?,?) ON CONFLICT(username) DO UPDATE SET role=excluded.role",
                (username, role),
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
                        (
                            user["id"],
                            item["name"],
                            digest(item["token"]),
                            iso(utcnow()),
                        ),
                    )

    @contextmanager
    def transaction(immediate=False):
        db = connect()
        try:
            db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def identity_for_username(username):
        return identities.get(
            username.casefold(),
            {"displayName": username, "slot": username.casefold()},
        )

    retention_per_slot = int(app.config["SAVE_SYNC_RETENTION_PER_SLOT"])
    backup_timeout = int(app.config["SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS"])

    def cleanup_canonical_versions():
        """Conserva las últimas N versiones de cada slot configurado."""
        with transaction(immediate=True) as db:
            # Purga first: marca como huérfanas las filas cuyo backup excedió el
            # timeout (p. ej. worker reemplazado sin su thread). Esto evita que
            # una versión protegida eternamente bloquee la retención.
            stale_before = iso(
                utcnow() - timedelta(seconds=backup_timeout + 60)
            )
            db.execute(
                "DELETE FROM pending_backups WHERE started_at < ?",
                (stale_before,),
            )
            rows = db.execute(
                "SELECT v.version,v.path,u.username FROM versions v "
                "JOIN users u ON u.id=v.updated_by ORDER BY v.version DESC"
            ).fetchall()
            pending_backups = {
                row[0] for row in db.execute("SELECT version FROM pending_backups")
            }
            kept_per_slot = {}
            for row in rows:
                slot = identity_for_username(row["username"])["slot"]
                kept = kept_per_slot.get(slot, 0)
                if kept >= retention_per_slot and row["version"] not in pending_backups:
                    db.execute(
                        "DELETE FROM versions WHERE version=?", (row["version"],)
                    )
                else:
                    kept_per_slot[slot] = kept + 1
            referenced = {
                storage / row["path"]
                for row in db.execute("SELECT path FROM versions").fetchall()
            }
            # El glob y los unlink permanecen bajo BEGIN IMMEDIATE. Upload y
            # restore mueven su ZIP final bajo el mismo lock, por lo que no
            # pueden publicar entre este snapshot y la reconciliación.
            candidates = set((storage / "backups").glob("save-v*.zip"))
            for path in candidates - referenced:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    # La metadata obsoleta se confirma igualmente. El ZIP
                    # huérfano se reintentará en el siguiente cleanup/arranque.
                    app.logger.exception("No se pudo eliminar ZIP obsoleto %s", path)

    # Recupera limpiezas interrumpidas y la tabla de backups pendientes.
    cleanup_canonical_versions()

    def terminate_process_group(process, sigterm_timeout=10, sigkill_timeout=10):
        """Envia SIGTERM al grupo de proceso del hijo (start_new_session) y, tras
        el periodo de gracia, SIGKILL al grupo completo. process.wait() solo
        vigila al proceso directo, por lo que un nieto que ignore SIGTERM
        quedaría si no se mata el grupo entero. Nunca propaga errores."""
        pgid = process.pid
        try:
            pgid = os.getpgid(process.pid)
        except (ProcessLookupError, PermissionError):
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=sigterm_timeout)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=sigkill_timeout)
        except subprocess.TimeoutExpired:
            app.logger.warning(
                "El proceso de backup (pid %s) no terminó tras SIGKILL",
                process.pid,
            )

    def arm_backup_marker(db, version):
        """Marca la versión como pendiente de backup cuando el hook está activo.
        Se llama dentro de la transacción de publicación/restore para que la
        protección contra la retención sea atómica con la creación de la
        versión."""
        if not str(app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"]).strip():
            return
        db.execute(
            "INSERT OR REPLACE INTO pending_backups(version,started_at) VALUES(?,?)",
            (version, iso(utcnow())),
        )

    def release_backup_marker(version, success, exit_code=0, timed_out=False, reason=None):
        """Desmarca el backup y audita el resultado. Best-effort: nunca invalida
        una publicación ya confirmada."""
        details = {
            "version": version,
            "exitCode": exit_code,
            "timedOut": 1 if timed_out else 0,
        }
        if reason:
            details["reason"] = reason
        try:
            with transaction(immediate=True) as db:
                db.execute(
                    "DELETE FROM pending_backups WHERE version=?", (version,)
                )
                audit(
                    db,
                    "backup_hook_completed" if success else "backup_hook_failed",
                    None,
                    success,
                    **details,
                )
        except Exception:
            app.logger.exception(
                "No se pudo registrar el resultado del backup de la versión %s",
                version,
            )

    def await_backup_result(process, version):
        exit_code = 0
        timed_out = False
        success = False
        try:
            exit_code = process.wait(timeout=backup_timeout)
            success = exit_code == 0
        except subprocess.TimeoutExpired:
            timed_out = True
            # El proceso arranca con start_new_session=True, así que su PGID es
            # su propio PID. Se termina el grupo entero para no dejar huérfanos
            # que sigan usando el ZIP publicado.
            terminate_process_group(process, sigterm_timeout=10)
            try:
                exit_code = process.wait(timeout=5)
                # timed_out ya implica fracaso; success se mantiene False.
            except subprocess.TimeoutExpired:
                exit_code = -1
                app.logger.warning(
                    "El backup externo de la versión %s no terminó tras SIGKILL",
                    version,
                )
        finally:
            release_backup_marker(version, success, exit_code, timed_out)
            try:
                cleanup_canonical_versions()
            except Exception:
                app.logger.exception(
                    "La limpieza post-backup falló; la versión %s se conserva",
                    version,
                )
            if not success or timed_out:
                app.logger.warning(
                    "El backup externo de la versión %s terminó con exit code %s%s",
                    version,
                    exit_code,
                    " (timeout)" if timed_out else "",
                )

    def run_post_publish_hook(version, relative_path, save_identity):
        """Lanza el backup externo; nunca invalida la publicación confirmada."""
        command = str(app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"]).strip()
        if not command:
            return
        env = os.environ.copy()
        env.update(
            {
                "SAVE_SYNC_PUBLISHED_VERSION": str(version),
                "SAVE_SYNC_PUBLISHED_PATH": str(storage / relative_path),
                "SAVE_SYNC_PUBLISHED_IDENTITY": save_identity,
                "SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS": str(backup_timeout),
            }
        )
        try:
            argv = shlex.split(command)
            if not argv:
                return
            process = subprocess.Popen(
                argv,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except Exception:
            # Popen()/shlex.split() falló: no hay proceso que esperar. La
            # versión ya está publicada; liberamos el marcador best-effort y
            # nunca devolvemos error al cliente.
            app.logger.exception(
                "Falló el hook post-publicación; la versión %s permanece publicada",
                version,
            )
            release_backup_marker(version, False, reason="hook_launch_failed")
            try:
                cleanup_canonical_versions()
            except Exception:
                app.logger.exception(
                    "La limpieza post-fallo-del-hook falló; la versión %s se conserva",
                    version,
                )
            return

        try:
            threading.Thread(
                target=await_backup_result,
                args=(process, version),
                daemon=True,
            ).start()
        except Exception:
            # La publicación ya confirmó (COMMIT hecho). Matamos el proceso
            # best-effort, liberamos el marcador y limpiamos, pero NUNCA
            # devolvemos 500: la partida se publicó correctamente.
            app.logger.exception(
                "No se pudo iniciar el supervisor de backup para la versión %s; "
                "la versión permanece publicada",
                version,
            )
            terminate_process_group(process)
            release_backup_marker(version, False, reason="thread_start_failed")
            try:
                cleanup_canonical_versions()
            except Exception:
                app.logger.exception(
                    "La limpieza post-fallo-del-supervisor falló; la versión %s se conserva",
                    version,
                )

    def audit(db, event, user=None, success=True, client_id=None, **details):
        db.execute(
            "INSERT INTO audit(event,user_id,at,success,client_id,details) VALUES(?,?,?,?,?,?)",
            (
                event,
                user["id"] if user else None,
                iso(utcnow()),
                int(success),
                client_id,
                json.dumps(details, separators=(",", ":")),
            ),
        )

    def web_auth(db):
        configured = app.config.get("SAVE_SYNC_PROXY_SECRET", "")
        supplied = request.headers.get("X-Save-Sync-Proxy-Secret", "")
        if not supplied and legacy_palworld:
            supplied = request.headers.get("X-Palworld-Proxy-Secret", "")
        if (
            not configured
            or not supplied
            or not hmac.compare_digest(configured, supplied)
        ):
            return None, "proxy_authentication_required"
        username = request.headers.get("X-authentik-username", "")
        if not username:
            return None, "identity_required"
        user = db.execute(
            "SELECT * FROM users WHERE username=? AND active=1", (username,)
        ).fetchone()
        if not user:
            return None, "web_user_not_allowed"
        return user, None

    def display_username(username):
        return identity_for_username(username)["displayName"]

    def display_name(user):
        return display_username(user["username"])

    def csrf_value(username):
        secret = app.config.get("SAVE_SYNC_CSRF_SECRET") or os.environ.get(
            "SAVE_SYNC_CSRF_SECRET", ""
        )
        if not secret:
            return None
        return hmac.new(
            secret.encode(), (game_key + ":" + username).encode(), hashlib.sha256
        ).hexdigest()

    def authenticate(require_admin=False):
        if app.config["SAVE_SYNC_REQUIRE_HTTPS"] and not request.is_secure:
            return None, error("https_required", "La API requiere HTTPS.", 403)
        db = connect()
        try:
            web_api_prefix = f"/games/{game_key}/api"
            alias_web = request.path.startswith(web_api_prefix + "/") or (
                legacy_palworld and request.path.startswith("/palworld/api/")
            )
            auth = request.headers.get("Authorization", "")
            user = None
            if not alias_web and auth.startswith("Bearer "):
                token_hash = digest(auth[7:])
                user = db.execute(
                    "SELECT u.*,t.id token_id FROM api_tokens t JOIN users u ON u.id=t.user_id WHERE t.token_hash=? AND t.revoked_at IS NULL AND u.active=1",
                    (token_hash,),
                ).fetchone()
                if user:
                    db.execute(
                        "UPDATE api_tokens SET last_used_at=? WHERE id=?",
                        (iso(utcnow()), user["token_id"]),
                    )
            elif alias_web:
                user, web_failure = web_auth(db)
                if web_failure == "web_user_not_allowed":
                    return None, error(
                        "web_user_not_allowed",
                        f"El usuario autenticado no está autorizado para {display_game}.",
                        403,
                    )
                if user and request.method not in {"GET", "HEAD", "OPTIONS"}:
                    expected = csrf_value(user["username"])
                    supplied = request.headers.get("X-CSRF-Token", "")
                    if not expected or not hmac.compare_digest(expected, supplied):
                        return None, error(
                            "csrf_failed", "Token CSRF ausente o no válido.", 403
                        )
            if not user:
                return None, error(
                    "authentication_required", "Se requiere autenticación válida.", 401
                )
            if require_admin and user["role"] != "admin":
                return None, error(
                    "forbidden", "Se requieren permisos administrativos.", 403
                )
            limit = int(app.config["SAVE_SYNC_RATE_LIMIT_PER_MINUTE"])
            window = int(time.time() // 60)
            identity = f"{user['id']}:{request.endpoint}"
            db.execute(
                "INSERT INTO rate_limits(identity,window,count) VALUES(?,?,1) ON CONFLICT(identity,window) DO UPDATE SET count=count+1",
                (identity, window),
            )
            if secrets.randbelow(100) == 0:
                db.execute("DELETE FROM rate_limits WHERE window<?", (window - 10,))
            count = db.execute(
                "SELECT count FROM rate_limits WHERE identity=? AND window=?",
                (identity, window),
            ).fetchone()[0]
            if count > limit:
                return None, error("rate_limit_exceeded", "Demasiadas peticiones.", 429)
            return user, None
        finally:
            db.close()

    def secured(admin=False):
        def outer(fn):
            @wraps(fn)
            def inner(*args, **kwargs):
                user, failure = authenticate(admin)
                if failure:
                    return failure
                g.save_sync_user = user
                return fn(*args, **kwargs)

            return inner

        return outer

    def current_version(db):
        return db.execute(
            "SELECT v.* FROM current_save c JOIN versions v ON v.version=c.version WHERE c.singleton=1"
        ).fetchone()

    def backup_status_snapshot(db):
        """Resume el estado observable del hook sin asumir que restic está sano."""
        current = current_version(db)
        latest_version = current["version"] if current else 0
        pending_rows = db.execute(
            "SELECT version,started_at FROM pending_backups ORDER BY version"
        ).fetchall()
        stale_before = utcnow() - timedelta(seconds=backup_timeout + 60)
        pending = []
        stale_pending = []
        for row in pending_rows:
            item = {"version": row["version"], "startedAt": row["started_at"]}
            try:
                is_stale = parse_iso(row["started_at"]) < stale_before
            except (AttributeError, TypeError, ValueError):
                # Un marcador ilegible tampoco debe presentarse como backup
                # activo: la observabilidad es deliberadamente conservadora.
                is_stale = True
            (stale_pending if is_stale else pending).append(item)

        attempts = []
        rows = db.execute(
            "SELECT event,at,success,details FROM audit "
            "WHERE event IN ('backup_hook_completed','backup_hook_failed') "
            "ORDER BY id DESC LIMIT 500"
        ).fetchall()
        for row in rows:
            try:
                details = json.loads(row["details"])
                version = int(details["version"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            attempts.append(
                {
                    "version": version,
                    "completedAt": row["at"],
                    "success": bool(row["success"]),
                    "exitCode": details.get("exitCode"),
                    "timedOut": bool(details.get("timedOut", False)),
                    "reason": details.get("reason"),
                }
            )

        last_attempt = attempts[0] if attempts else None
        last_completed = next(
            (attempt for attempt in attempts if attempt["success"]), None
        )
        current_attempt = next(
            (attempt for attempt in attempts if attempt["version"] == latest_version),
            None,
        )
        current_pending = any(
            item["version"] == latest_version for item in pending
        )
        current_stale_pending = any(
            item["version"] == latest_version for item in stale_pending
        )
        enabled = bool(str(app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"]).strip())
        if not current:
            state = "not_initialized"
        elif current_pending:
            state = "pending"
        elif current_attempt:
            state = "completed" if current_attempt["success"] else "failed"
        elif enabled:
            state = "unknown"
        else:
            state = "disabled"

        return {
            "enabled": enabled,
            "state": state,
            "latestPublishedVersion": latest_version,
            "latestVersionBackedUp": bool(
                current_attempt and current_attempt["success"]
            ),
            "pending": current_pending,
            "pendingVersions": pending,
            "stalePending": current_stale_pending,
            "stalePendingVersions": stale_pending,
            "lastAttempt": last_attempt,
            "lastCompleted": last_completed,
        }

    def normalize_save_identity(value):
        return normalize_identity_value(value)

    def active_lock(db, clear_expired=True):
        row = db.execute(
            "SELECT l.*,u.username FROM active_lock l JOIN users u ON u.id=l.owner_user_id WHERE singleton=1"
        ).fetchone()
        if row and parse_iso(row["expires_at"]) <= utcnow():
            if clear_expired:
                db.execute("DELETE FROM active_lock WHERE singleton=1")
                audit(
                    db,
                    "lock_expired",
                    success=True,
                    client_id=row["client_id"],
                    owner=row["owner_label"],
                )
            return None
        return row

    def lock_public(row):
        return {
            "owner": row["owner_label"],
            "createdAt": row["created_at"],
            "lastHeartbeatAt": row["last_heartbeat_at"],
            "expiresAt": row["expires_at"],
        }

    def validate_zip(path):
        if path.suffix.lower() != ".zip":
            raise ValueError("zip_extension")
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > int(app.config["SAVE_SYNC_MAX_ZIP_ENTRIES"]):
                    raise ValueError("zip_too_many_entries")
                total = 0
                compressed_total = 0
                names = set()
                for entry in entries:
                    normalized = entry.filename.replace("\\", "/")
                    if normalized in names:
                        raise ValueError("zip_duplicate_entry")
                    names.add(normalized)
                    member = PurePosixPath(normalized)
                    if (
                        member.is_absolute()
                        or ".." in member.parts
                        or (member.parts and ":" in member.parts[0])
                    ):
                        raise ValueError("zip_unsafe_path")
                    mode = entry.external_attr >> 16
                    file_type = stat.S_IFMT(mode)
                    if stat.S_ISLNK(mode) or (
                        file_type and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))
                    ):
                        raise ValueError("zip_special_file")
                    if entry.flag_bits & 0x1:
                        raise ValueError("zip_encrypted")
                    if entry.compress_type not in {
                        zipfile.ZIP_STORED,
                        zipfile.ZIP_DEFLATED,
                    }:
                        raise ValueError("zip_compression_method")
                    total += entry.file_size
                    compressed_total += entry.compress_size
                    if total > int(app.config["SAVE_SYNC_MAX_UNCOMPRESSED_SIZE"]):
                        raise ValueError("zip_uncompressed_too_large")
                    ratio = entry.file_size / max(entry.compress_size, 1)
                    if ratio > int(app.config["SAVE_SYNC_MAX_COMPRESSION_RATIO"]):
                        raise ValueError("zip_compression_ratio")
                if total / max(compressed_total, 1) > int(
                    app.config["SAVE_SYNC_MAX_COMPRESSION_RATIO"]
                ):
                    raise ValueError("zip_compression_ratio")
                bad = archive.testzip()
                if bad:
                    raise ValueError("zip_corrupt")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
            raise ValueError("zip_invalid") from exc

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc):
        return error(
            "upload_too_large",
            "El archivo supera el límite configurado.",
            413,
            {"maxBytes": int(app.config["SAVE_SYNC_MAX_UPLOAD_SIZE"])},
        )

    @app.errorhandler(500)
    def internal_error(_exc):
        if request.path.startswith(
            (f"/api/games/{game_key}", f"/games/{game_key}/api")
        ) or (legacy_palworld and request.path.startswith(("/api/palworld", "/palworld/api"))):
            return error(
                "internal_error",
                "Error interno; no se ha publicado ninguna versión.",
                500,
            )
        return Response("Error interno", 500, content_type="text/plain; charset=utf-8")

    @app.errorhandler(404)
    def not_found(_exc):
        if request.path.startswith(
            (f"/api/games/{game_key}", f"/games/{game_key}/api")
        ) or (legacy_palworld and request.path.startswith(("/api/palworld", "/palworld/api"))):
            return error("not_found", "Recurso no encontrado.", 404)
        return _exc

    @app.after_request
    def private_cache(response):
        if request.path.startswith((f"/api/games/{game_key}", f"/games/{game_key}")) or (
            legacy_palworld and request.path.startswith(("/api/palworld", "/palworld"))
        ):
            response.headers.setdefault("Cache-Control", "private, no-store")
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    @app.get("/healthz")
    def healthz():
        try:
            with connect() as db:
                db.execute("SELECT 1").fetchone()
            return jsonify(ok=True)
        except sqlite3.Error:
            return error("storage_unavailable", "Base de datos no disponible.", 503)

    def routes(rule, **options):
        def deco(fn):
            endpoint = options.pop("endpoint", fn.__name__)
            app.add_url_rule(
                f"/api/games/{game_key}" + rule,
                endpoint + "_api",
                fn,
                **options,
            )
            app.add_url_rule(
                f"/games/{game_key}/api" + rule,
                endpoint + "_web",
                fn,
                **options,
            )
            if legacy_palworld:
                app.add_url_rule(
                    "/api/palworld" + rule,
                    endpoint + "_palworld_api",
                    fn,
                    **options,
                )
                app.add_url_rule(
                    "/palworld/api" + rule,
                    endpoint + "_palworld_web",
                    fn,
                    **options,
                )
            return fn

        return deco

    def identity_json(value):
        payload = {"saveIdentity": value, identity_field: value}
        if legacy_palworld:
            payload["worldGuid"] = value
        return payload

    def identity_conflict_details(expected, received):
        details = {
            "identityField": identity_field,
            "expectedSaveIdentity": expected,
            "receivedSaveIdentity": received,
        }
        if legacy_palworld:
            details.update(expectedWorldGuid=expected, receivedWorldGuid=received)
        return details

    identity_conflict_code = (
        "world_guid_conflict" if legacy_palworld else "save_identity_conflict"
    )
    identity_conflict_message = (
        "El ZIP pertenece a un mundo de Palworld diferente."
        if legacy_palworld
        else f"El ZIP pertenece a otra partida de {display_game}."
    )

    def add_download_headers(response, version):
        response.headers["X-Save-Sync-Version"] = str(version["version"])
        response.headers["X-Save-Sync-SHA256"] = version["sha256"]
        response.headers["X-Save-Sync-Identity"] = version["save_identity"]
        if legacy_palworld:
            response.headers["X-Palworld-Version"] = str(version["version"])
            response.headers["X-Palworld-SHA256"] = version["sha256"]
            response.headers["X-Palworld-World-Guid"] = version["save_identity"]
        return response

    @routes("/status", methods=["GET"])
    @secured()
    def status_view():
        with transaction(immediate=True) as db:
            version = current_version(db)
            lock = active_lock(db)
            result = {
                "gameKey": game_key,
                "game": display_game,
                "identityField": identity_field,
                "initialized": bool(version),
                "version": version["version"] if version else 0,
                "sha256": version["sha256"] if version else None,
                "size": version["size"] if version else 0,
                "updatedAt": version["updated_at"] if version else None,
                "updatedBy": display_username(
                    db.execute(
                        "SELECT username FROM users WHERE id=?",
                        (version["updated_by"],),
                    ).fetchone()[0]
                )
                if version
                else None,
                "locked": bool(lock),
                "lock": lock_public(lock) if lock else None,
            }
            result.update(identity_json(version["save_identity"] if version else None))
        return jsonify(result)

    @routes("/backup-status", methods=["GET"])
    @secured()
    def backup_status_view():
        with transaction() as db:
            result = backup_status_snapshot(db)
        result.update(gameKey=game_key, game=display_game)
        return jsonify(result)

    @routes("/lock", methods=["POST"])
    @secured()
    def acquire_lock():
        data = request.get_json(silent=True) or {}
        owner = str(data.get("owner", "")).strip()
        client_id = str(data.get("clientId", "")).strip()
        if not owner or not client_id or len(owner) > 100 or len(client_id) > 200:
            return error("invalid_request", "owner y clientId son obligatorios.", 400)
        canonical_owner = display_name(g.save_sync_user)
        if owner.casefold() != canonical_owner.casefold():
            return error(
                "owner_mismatch",
                "owner no coincide con el usuario autenticado.",
                403,
                {"expectedOwner": canonical_owner},
            )
        session_id = secrets.token_urlsafe(48)
        now = utcnow()
        expires = now + timedelta(seconds=int(app.config["SAVE_SYNC_LOCK_TTL_SECONDS"]))
        with transaction(immediate=True) as db:
            existing = active_lock(db)
            if existing:
                audit(
                    db,
                    "lock_rejected",
                    g.save_sync_user,
                    False,
                    client_id,
                    owner=existing["owner_label"],
                    expiresAt=existing["expires_at"],
                )
                return error(
                    "lock_occupied",
                    "La partida está siendo utilizada.",
                    409,
                    {
                        "owner": existing["owner_label"],
                        "expiresAt": existing["expires_at"],
                    },
                )
            version = current_version(db)
            base = version["version"] if version else 0
            db.execute(
                "INSERT INTO active_lock(singleton,session_hash,owner_user_id,token_id,owner_label,client_id,base_version,created_at,last_heartbeat_at,expires_at) VALUES(1,?,?,?,?,?,?,?,?,?)",
                (
                    digest(session_id),
                    g.save_sync_user["id"],
                    g.save_sync_user["token_id"]  # noqa: SIM401
                    if "token_id" in g.save_sync_user
                    else None,
                    canonical_owner,
                    client_id,
                    base,
                    iso(now),
                    iso(now),
                    iso(expires),
                ),
            )
            audit(
                db, "lock_acquired", g.save_sync_user, True, client_id, baseVersion=base
            )
        lock_response = {
            "sessionId": session_id,
            "baseVersion": base,
            "expiresAt": iso(expires),
            "gameKey": game_key,
        }
        lock_response.update(identity_json(version["save_identity"] if version else None))
        return jsonify(lock_response), 201

    def session_action(event, delete=False):
        data = request.get_json(silent=True) or {}
        sid = str(data.get("sessionId", ""))
        if not sid:
            return error("invalid_request", "sessionId es obligatorio.", 400)
        now = utcnow()
        with transaction(immediate=True) as db:
            raw = db.execute("SELECT * FROM active_lock WHERE singleton=1").fetchone()
            if (
                raw
                and parse_iso(raw["expires_at"]) <= now
                and hmac.compare_digest(raw["session_hash"], digest(sid))
            ):
                db.execute("DELETE FROM active_lock WHERE singleton=1")
                audit(db, event, g.save_sync_user, False, reason="lock_expired")
                return error("lock_expired", "El bloqueo ha caducado.", 409)
            row = active_lock(db)
            same_token = row and (
                row["token_id"] is None
                or (
                    "token_id" in g.save_sync_user
                    and row["token_id"] == g.save_sync_user["token_id"]
                )
            )
            if (
                not row
                or not hmac.compare_digest(row["session_hash"], digest(sid))
                or row["owner_user_id"] != g.save_sync_user["id"]
                or not same_token
            ):
                audit(db, event, g.save_sync_user, False, reason="invalid_session")
                return error(
                    "invalid_session",
                    "La sesión no existe, ha caducado o no pertenece al usuario.",
                    409,
                )
            if delete:
                db.execute("DELETE FROM active_lock WHERE singleton=1")
                expires = None
            else:
                expires = now + timedelta(
                    seconds=int(app.config["SAVE_SYNC_LOCK_TTL_SECONDS"])
                )
                db.execute(
                    "UPDATE active_lock SET last_heartbeat_at=?,expires_at=? WHERE singleton=1",
                    (iso(now), iso(expires)),
                )
            audit(db, event, g.save_sync_user, True, row["client_id"])
        return jsonify(ok=True, **({"expiresAt": iso(expires)} if expires else {}))

    @routes("/heartbeat", methods=["POST"])
    @secured()
    def heartbeat():
        return session_action("heartbeat")

    @routes("/unlock", methods=["POST"])
    @secured()
    def unlock():
        return session_action("unlock", True)

    @routes("/download", methods=["GET"])
    @secured()
    def download():
        with transaction() as db:
            row = current_version(db)
            if not row:
                return error(
                    "save_not_initialized", "Todavía no existe una partida remota.", 404
                )
            path = storage / row["path"]
            audit(db, "download", g.save_sync_user, True, version=row["version"])
        if not path.is_file():
            return error(
                "storage_unavailable", "La versión registrada no está disponible.", 503
            )
        response = send_file(
            path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{game_key}-save-v{row['version']}.zip",
            conditional=True,
        )
        return add_download_headers(response, row)

    @routes("/upload", methods=["POST"])
    @secured()
    def upload():
        upload_file = request.files.get("file")
        sid = request.form.get("sessionId", "")
        claimed_hash = request.form.get("sha256", "").lower()
        received_save_identity = str(
            request.form.get(identity_field)
            or request.form.get("saveIdentity")
            or (request.form.get("worldGuid") if legacy_palworld else "")
            or ""
        ).strip()
        save_identity = normalize_save_identity(received_save_identity)
        try:
            base = int(request.form.get("baseVersion", ""))
        except ValueError:
            base = -1
        if not upload_file or not sid or base < 0 or len(claimed_hash) != 64:
            return error(
                "invalid_request",
                f"file, sessionId, baseVersion, sha256 y {identity_field} son obligatorios.",
                400,
            )
        if not save_identity:
            details = {
                "identityField": identity_field,
                "receivedSaveIdentity": received_save_identity[:128],
            }
            if legacy_palworld:
                details["receivedWorldGuid"] = received_save_identity[:128]
            return error(
                "invalid_save_identity",
                f"{identity_field} no cumple el formato configurado.",
                400,
                details,
            )
        suffix = Path(upload_file.filename or "").suffix.lower()
        fd, tmp_name = tempfile.mkstemp(
            prefix="upload-", suffix=suffix, dir=storage / "temporary"
        )
        os.close(fd)
        tmp = Path(tmp_name)
        published_final = None

        def audit_upload_failure(reason):
            with transaction(immediate=True) as failure_db:
                audit(
                    failure_db,
                    "upload_failed",
                    g.save_sync_user,
                    False,
                    reason=reason,
                    baseVersion=base,
                    saveIdentity=save_identity,
                )

        try:
            hasher = hashlib.sha256()
            size = 0
            with tmp.open("wb") as target:
                while chunk := upload_file.stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > int(app.config["SAVE_SYNC_MAX_UPLOAD_SIZE"]):
                        audit_upload_failure("upload_too_large")
                        return error(
                            "upload_too_large",
                            "El archivo supera el límite configurado.",
                            413,
                        )
                    hasher.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            actual = hasher.hexdigest()
            if not hmac.compare_digest(actual, claimed_hash):
                audit_upload_failure("sha256_mismatch")
                return error(
                    "sha256_mismatch",
                    "El SHA-256 no coincide.",
                    422,
                    {"calculatedSha256": actual},
                )
            try:
                validate_zip(tmp)
            except ValueError as exc:
                audit_upload_failure(str(exc))
                return error(
                    str(exc), "El ZIP no supera las validaciones de seguridad.", 422
                )
            with transaction(immediate=True) as db:
                audit(
                    db,
                    "upload_started",
                    g.save_sync_user,
                    True,
                    baseVersion=base,
                    size=size,
                )
                current = current_version(db)
                expected = current["version"] if current else 0
                expected_save_identity = current["save_identity"] if current else None
                if expected_save_identity and not hmac.compare_digest(
                    expected_save_identity, save_identity
                ):
                    audit(
                        db,
                        identity_conflict_code,
                        g.save_sync_user,
                        False,
                        **identity_conflict_details(
                            expected_save_identity, save_identity
                        ),
                    )
                    return error(
                        identity_conflict_code,
                        identity_conflict_message,
                        409,
                        identity_conflict_details(
                            expected_save_identity, save_identity
                        ),
                    )
                if base != expected:
                    audit(
                        db,
                        "version_conflict",
                        g.save_sync_user,
                        False,
                        expected=expected,
                        received=base,
                        saveIdentity=save_identity,
                        **({"worldGuid": save_identity} if legacy_palworld else {}),
                    )
                    return error(
                        "version_conflict",
                        "La versión remota ha cambiado.",
                        409,
                        {"expectedBaseVersion": expected, "receivedBaseVersion": base},
                    )
                lock = active_lock(db)
                same_token = lock and (
                    lock["token_id"] is None
                    or (
                        "token_id" in g.save_sync_user
                        and lock["token_id"] == g.save_sync_user["token_id"]
                    )
                )
                if (
                    not lock
                    or lock["owner_user_id"] != g.save_sync_user["id"]
                    or not same_token
                    or not hmac.compare_digest(lock["session_hash"], digest(sid))
                ):
                    audit(
                        db,
                        "upload_failed",
                        g.save_sync_user,
                        False,
                        reason="invalid_session",
                    )
                    return error(
                        "invalid_session",
                        "La sesión no existe, ha caducado o no pertenece al usuario.",
                        409,
                    )
                if lock["base_version"] != expected:
                    audit(
                        db,
                        "version_conflict",
                        g.save_sync_user,
                        False,
                        expected=expected,
                        received=base,
                        saveIdentity=save_identity,
                        **({"worldGuid": save_identity} if legacy_palworld else {}),
                    )
                    return error(
                        "version_conflict",
                        "La versión remota ha cambiado.",
                        409,
                        {"expectedBaseVersion": expected, "receivedBaseVersion": base},
                    )
                new_version = expected + 1
                relative = f"backups/save-v{new_version:06d}.zip"
                final = storage / relative
                if final.exists():
                    referenced = db.execute(
                        "SELECT 1 FROM versions WHERE path=?", (relative,)
                    ).fetchone()
                    if referenced:
                        raise RuntimeError("version_path_exists")
                    final.unlink()
                os.replace(tmp, final)
                fsync_directory(final.parent)
                published_final = final
                db.execute(
                    "INSERT INTO versions(version,path,sha256,size,updated_by,updated_at,base_version,save_identity) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        new_version,
                        relative,
                        actual,
                        size,
                        g.save_sync_user["id"],
                        iso(utcnow()),
                        base,
                        save_identity,
                    ),
                )
                db.execute(
                    "INSERT INTO current_save(singleton,version) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET version=excluded.version",
                    (new_version,),
                )
                # Marca de backup ATÓMICA con la publicación: la protección
                # contra la retención debe existir desde el mismo instante en
                # que la versión es viable. No insertarlo aquí fuera permitiría
                # que otro publish del mismo slot eliminara el ZIP antes de que
                # run_post_publish_hook() armara el marcador.
                arm_backup_marker(db, new_version)
                db.execute("DELETE FROM active_lock WHERE singleton=1")
                audit(
                    db,
                    "upload_completed",
                    g.save_sync_user,
                    True,
                    version=new_version,
                    previousVersion=expected,
                    **identity_json(save_identity),
                )
                updated_at = db.execute(
                    "SELECT updated_at FROM versions WHERE version=?", (new_version,)
                ).fetchone()[0]
            # A partir de aquí el ZIP es la versión vigente confirmada. Nunca se
            # compensa aunque la limpieza posterior falle.
            published_final = None
            try:
                cleanup_canonical_versions()
            except Exception:
                app.logger.exception(
                    "La limpieza post-publicación falló; la versión confirmada se conserva"
                )
            run_post_publish_hook(new_version, relative, save_identity)
            result = {
                "ok": True,
                "previousVersion": base,
                "version": new_version,
                "sha256": actual,
                "size": size,
                "updatedAt": updated_at,
                "gameKey": game_key,
            }
            result.update(identity_json(save_identity))
            return jsonify(result), 201
        except Exception:
            if published_final is not None:
                published_final.unlink(missing_ok=True)
            raise
        finally:
            tmp.unlink(missing_ok=True)

    @routes("/history", methods=["GET"])
    @secured()
    def history():
        with transaction() as db:
            rows = db.execute(
                "SELECT v.*,u.username FROM versions v JOIN users u ON u.id=v.updated_by ORDER BY version DESC"
            ).fetchall()
        versions = []
        for r in rows:
            item = {
                    "version": r["version"],
                    "updatedBy": display_username(r["username"]),
                    "updatedAt": r["updated_at"],
                    "size": r["size"],
                    "sha256": r["sha256"],
                    "baseVersion": r["base_version"],
                    "restoredFromVersion": r["restored_from_version"],
                }
            item.update(identity_json(r["save_identity"]))
            versions.append(item)
        return jsonify(gameKey=game_key, identityField=identity_field, versions=versions)

    @routes("/history/<int:version>/download", methods=["GET"])
    @secured(admin=True)
    def history_download(version):
        with transaction() as db:
            row = db.execute(
                "SELECT * FROM versions WHERE version=?", (version,)
            ).fetchone()
            if not row:
                return error("version_not_found", "Versión no encontrada.", 404)
            audit(db, "backup_download", g.save_sync_user, True, version=version)
        path = storage / row["path"]
        if not path.is_file():
            return error(
                "storage_unavailable", "La versión registrada no está disponible.", 503
            )
        response = send_file(
            path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{game_key}-save-v{version}.zip",
            conditional=True,
        )
        add_download_headers(response, row)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @routes("/history/<int:version>/restore", methods=["POST"])
    @secured(admin=True)
    def restore(version):
        final = None
        temp = None
        try:
            # Lectura inicial breve; el hash y la copia grande se realizan sin
            # retener el bloqueo de escritura de SQLite.
            with transaction(immediate=True) as db:
                lock = active_lock(db)
                if lock:
                    return error(
                        "lock_occupied",
                        "No se puede restaurar durante una sesión activa.",
                        409,
                        {"owner": lock["owner_label"], "expiresAt": lock["expires_at"]},
                    )
                source_row = db.execute(
                    "SELECT * FROM versions WHERE version=?", (version,)
                ).fetchone()
                source = dict(source_row) if source_row else None
                if not source:
                    return error("version_not_found", "Versión no encontrada.", 404)
                initial_current = current_version(db)
                initial_current_version = (
                    initial_current["version"] if initial_current else 0
                )
                if initial_current and not hmac.compare_digest(
                    initial_current["save_identity"], source["save_identity"]
                ):
                    audit(
                        db,
                        identity_conflict_code,
                        g.save_sync_user,
                        False,
                        **identity_conflict_details(
                            initial_current["save_identity"],
                            source["save_identity"],
                        ),
                        operation="backup_restore",
                    )
                    return error(
                        identity_conflict_code,
                        identity_conflict_message,
                        409,
                        identity_conflict_details(
                            initial_current["save_identity"], source["save_identity"]
                        ),
                    )
                source_path = storage / source["path"]

            if not source_path.is_file():
                return error(
                    "backup_integrity_failed",
                    "El backup no está disponible o no supera integridad.",
                    503,
                )
            temp = storage / "temporary" / f"restore-{secrets.token_hex(12)}.zip"
            source_hash = hashlib.sha256()
            with source_path.open("rb") as source_stream, temp.open("wb") as target:
                while chunk := source_stream.read(1024 * 1024):
                    source_hash.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if source_hash.hexdigest() != source["sha256"]:
                return error(
                    "backup_integrity_failed",
                    "El backup no está disponible o no supera integridad.",
                    503,
                )

            with transaction(immediate=True) as db:
                lock = active_lock(db)
                if lock:
                    return error(
                        "lock_occupied",
                        "Se inició una sesión mientras se preparaba la restauración.",
                        409,
                        {"owner": lock["owner_label"], "expiresAt": lock["expires_at"]},
                    )
                current = current_version(db)
                current_number = current["version"] if current else 0
                if current and not hmac.compare_digest(
                    current["save_identity"], source["save_identity"]
                ):
                    audit(
                        db,
                        identity_conflict_code,
                        g.save_sync_user,
                        False,
                        **identity_conflict_details(
                            current["save_identity"], source["save_identity"]
                        ),
                        operation="backup_restore",
                    )
                    return error(
                        identity_conflict_code,
                        identity_conflict_message,
                        409,
                        identity_conflict_details(
                            current["save_identity"], source["save_identity"]
                        ),
                    )
                unchanged_source = db.execute(
                    "SELECT path,sha256,size,save_identity FROM versions WHERE version=?",
                    (version,),
                ).fetchone()
                if (
                    current_number != initial_current_version
                    or not unchanged_source
                    or unchanged_source["path"] != source["path"]
                    or unchanged_source["sha256"] != source["sha256"]
                    or unchanged_source["save_identity"] != source["save_identity"]
                ):
                    audit(
                        db,
                        "version_conflict",
                        g.save_sync_user,
                        False,
                        expected=current_number,
                        received=initial_current_version,
                        saveIdentity=current["save_identity"] if current else None,
                        **(
                            {"worldGuid": current["save_identity"] if current else None}
                            if legacy_palworld
                            else {}
                        ),
                        operation="backup_restore",
                    )
                    return error(
                        "version_conflict",
                        "El estado remoto cambió mientras se preparaba la restauración.",
                        409,
                        {
                            "expectedBaseVersion": current_number,
                            "receivedBaseVersion": initial_current_version,
                        },
                    )
                new_version = current_number + 1
                relative = f"backups/save-v{new_version:06d}.zip"
                final = storage / relative
                if (
                    final.exists()
                    and not db.execute(
                        "SELECT 1 FROM versions WHERE path=?", (relative,)
                    ).fetchone()
                ):
                    final.unlink()
                os.replace(temp, final)
                fsync_directory(final.parent)
                now = iso(utcnow())
                db.execute(
                    "INSERT INTO versions(version,path,sha256,size,updated_by,updated_at,base_version,restored_from_version,save_identity) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        new_version,
                        relative,
                        source["sha256"],
                        source["size"],
                        g.save_sync_user["id"],
                        now,
                        current_number,
                        version,
                        source["save_identity"],
                    ),
                )
                db.execute(
                    "INSERT INTO current_save VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET version=excluded.version",
                    (new_version,),
                )
                # Marcador de backup atómico con la restauración publicada.
                arm_backup_marker(db, new_version)
                audit(
                    db,
                    "backup_restored",
                    g.save_sync_user,
                    True,
                    restoredFrom=version,
                    version=new_version,
                    **identity_json(source["save_identity"]),
                )
        except Exception:
            if final:
                final.unlink(missing_ok=True)
            raise
        finally:
            if temp:
                temp.unlink(missing_ok=True)
        try:
            cleanup_canonical_versions()
        except Exception:
            app.logger.exception(
                "La limpieza posterior a restauración falló; la versión confirmada se conserva"
            )
        run_post_publish_hook(new_version, relative, source["save_identity"])
        result = {
            "ok": True,
            "version": new_version,
            "restoredFromVersion": version,
            "sha256": source["sha256"],
            "size": source["size"],
            "updatedAt": now,
            "gameKey": game_key,
        }
        result.update(identity_json(source["save_identity"]))
        return jsonify(result), 201

    @routes("/history/<int:version>", methods=["DELETE"])
    @secured(admin=True)
    def delete_version(version):
        with transaction(immediate=True) as db:
            current = current_version(db)
            row = db.execute(
                "SELECT * FROM versions WHERE version=?", (version,)
            ).fetchone()
            if not row:
               return error("version_not_found", "Versión no encontrada.", 404)
            if version == current["version"]:
                return error(
                    "version_current",
                    "La versión actual no puede eliminarse.",
                    409,
                )
            pending = db.execute(
                "SELECT 1 FROM pending_backups WHERE version=?", (version,)
            ).fetchone()
            if pending:
                return error(
                    "backup_in_progress",
                    "La versión tiene un backup externo en curso.",
                    409,
                    {"version": version},
                )
            db.execute("DELETE FROM versions WHERE version=?", (version,))
            audit(db, "backup_deleted", g.save_sync_user, True, version=version)
        (storage / row["path"]).unlink(missing_ok=True)
        return jsonify(ok=True)

    @routes("/admin/force-unlock", methods=["POST"])
    @secured(admin=True)
    def force_unlock():
        data = request.get_json(silent=True) or {}
        reason = str(data.get("reason", "")).strip()
        if len(reason) < 5 or len(reason) > 500:
            return error(
                "invalid_request", "reason es obligatorio (5-500 caracteres).", 400
            )
        with transaction(immediate=True) as db:
            row = active_lock(db)
            if row:
                db.execute("DELETE FROM active_lock WHERE singleton=1")
            audit(
                db,
                "admin_force_unlock",
                g.save_sync_user,
                True,
                previousOwner=row["owner_label"] if row else None,
                reason=reason,
            )
        return jsonify(ok=True, hadActiveLock=bool(row))

    @routes("/admin/tokens", methods=["GET", "POST"])
    @secured(admin=True)
    def tokens():
        if request.method == "GET":
            with transaction() as db:
                rows = db.execute(
                    "SELECT t.id,t.name,t.created_at,t.last_used_at,t.revoked_at,u.username FROM api_tokens t JOIN users u ON u.id=t.user_id ORDER BY t.id"
                ).fetchall()
            return jsonify(tokens=[dict(r) for r in rows])
        data = request.get_json(silent=True) or {}
        username = str(data.get("username", ""))
        name = str(data.get("name", "")).strip()
        if not username or not name:
            return error("invalid_request", "username y name son obligatorios.", 400)
        token = "pws_" + secrets.token_urlsafe(36)
        with transaction(immediate=True) as db:
            user = db.execute(
                "SELECT * FROM users WHERE username=? AND active=1", (username,)
            ).fetchone()
            if not user:
                return error("user_not_found", "Usuario no encontrado.", 404)
            cursor = db.execute(
                "INSERT INTO api_tokens(user_id,name,token_hash,created_at) VALUES(?,?,?,?)",
                (user["id"], name, digest(token), iso(utcnow())),
            )
            audit(
                db,
                "token_created",
                g.save_sync_user,
                True,
                tokenId=cursor.lastrowid,
                username=username,
            )
        return jsonify(
            id=cursor.lastrowid, token=token, username=username, name=name
        ), 201

    @routes("/admin/tokens/<int:token_id>", methods=["DELETE"])
    @secured(admin=True)
    def revoke_token(token_id):
        with transaction(immediate=True) as db:
            changed = db.execute(
                "UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (iso(utcnow()), token_id),
            ).rowcount
            if not changed:
                return error("token_not_found", "Token activo no encontrado.", 404)
            audit(db, "token_revoked", g.save_sync_user, True, tokenId=token_id)
        return jsonify(ok=True)

    @routes("/admin/audit", methods=["GET"])
    @secured(admin=True)
    def audit_log():
        limit = min(max(request.args.get("limit", 100, type=int), 1), 500)
        with transaction() as db:
            rows = db.execute(
                "SELECT a.id,a.event,a.at,a.success,a.client_id,a.details,u.username FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return jsonify(
            events=[
                {
                    **dict(r),
                    "success": bool(r["success"]),
                    "details": json.loads(r["details"]),
                }
                for r in rows
            ]
        )

    def panel():
        db = connect()
        try:
            user, web_failure = web_auth(db)
        finally:
            db.close()
        if web_failure == "web_user_not_allowed":
            return Response(
                f"Usuario no autorizado para {display_game}",
                403,
                content_type="text/plain; charset=utf-8",
            )
        if not user:
            return Response(
                "Autenticación requerida",
                401,
                content_type="text/plain; charset=utf-8",
            )
        csrf = csrf_value(user["username"]) or ""
        panel_html = (
            PANEL_HTML.replace("__USER__", html.escape(user["username"], quote=True))
            .replace("__ROLE__", user["role"])
            .replace("__CSRF__", csrf)
            .replace("__GAME__", html.escape(display_game, quote=True))
            .replace("__IDENTITY_LABEL__", html.escape(identity_label, quote=True))
            .replace("__WEB_API_PREFIX__", f"/games/{game_key}/api")
        )
        return Response(
            panel_html,
            content_type="text/html; charset=utf-8",
        )

    app.add_url_rule(f"/games/{game_key}", "game_panel", panel, methods=["GET"])
    app.add_url_rule(
        f"/games/{game_key}/", "game_panel_slash", panel, methods=["GET"]
    )
    if legacy_palworld:
        app.add_url_rule("/palworld", "palworld_panel", panel, methods=["GET"])
        app.add_url_rule(
            "/palworld/", "palworld_panel_slash", panel, methods=["GET"]
        )

    return app


PANEL_HTML = r"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>__GAME__ · Save Sync</title><style>
:root{color-scheme:dark;font-family:system-ui;background:#10141b;color:#eef2f8}body{max-width:980px;margin:3rem auto;padding:0 1rem}header,.card{background:#19212d;border:1px solid #344154;border-radius:14px;padding:1.2rem;margin:1rem 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.8rem}.label{color:#9eabc0;font-size:.85rem}.value{font-size:1.1rem;overflow-wrap:anywhere}button,a.button{background:#5b7cfa;color:white;border:0;border-radius:8px;padding:.7rem 1rem;text-decoration:none;cursor:pointer}.busy,.backup-pending{color:#ffbf69}.free,.backup-completed{color:#72dfa1}.backup-failed,.backup-unknown{color:#ff7b86}.backup-disabled,.backup-not_initialized{color:#9eabc0}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:.55rem;border-bottom:1px solid #344154}code{font-size:.78rem}</style></head><body>
<header><h1>Sincronización __GAME__</h1><div>Usuario: __USER__ · Rol: __ROLE__</div></header><section class="card"><h2 id="state">Cargando…</h2><div class="grid" id="facts"></div><p id="lock"></p><a class="button" href="__WEB_API_PREFIX__/download">Descargar última versión</a> <button id="force" hidden>Forzar desbloqueo</button></section><section class="card"><h2>Backup externo</h2><div class="grid" id="backupFacts"></div><p id="backupState">Cargando…</p></section><section class="card"><h2>Historial</h2><table><thead><tr><th>Versión</th><th>__IDENTITY_LABEL__</th><th>Usuario</th><th>Fecha</th><th>Tamaño</th><th>SHA-256</th><th>Acciones</th></tr></thead><tbody id="history"></tbody></table></section><section class="card" id="tokensCard" hidden><h2>Tokens API</h2><p>El token nuevo se muestra una sola vez.</p><input id="tokenUser" placeholder="Usuario autorizado"><input id="tokenName" placeholder="Nombre del ordenador"><button id="createToken">Crear token</button><pre id="newToken"></pre><div id="tokens"></div></section>
<script>
const csrf='__CSRF__',role='__ROLE__';
const headers={'X-CSRF-Token':csrf,'Content-Type':'application/json'};
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const safeInt=value=>Number.isSafeInteger(Number(value))?Number(value):0;
async function mutate(url,method='POST',body={}){const r=await fetch(url,{method,headers,body:method==='DELETE'?undefined:JSON.stringify(body)});const j=await r.json();if(!r.ok)alert(j.message||'Error');return [r,j]}
async function load(){
 const backup=fetch('__WEB_API_PREFIX__/backup-status').then(async r=>r.ok?await r.json():null).catch(()=>null);
 const [s,h,b]=await Promise.all([fetch('__WEB_API_PREFIX__/status').then(r=>r.json()),fetch('__WEB_API_PREFIX__/history').then(r=>r.json()),backup]);
 document.querySelector('#state').textContent=s.locked?'Estado: en uso':'Estado: disponible';document.querySelector('#state').className=s.locked?'busy':'free';
 document.querySelector('#facts').innerHTML=[['Versión',s.version],['__IDENTITY_LABEL__',s.saveIdentity||'—'],['Última actualización',s.updatedAt||'Sin inicializar'],['Último jugador',s.updatedBy||'—'],['Tamaño',s.size+' bytes'],['SHA-256',s.sha256||'—']].map(x=>`<div><div class=label>${esc(x[0])}</div><div class=value>${esc(x[1])}</div></div>`).join('');
 document.querySelector('#lock').textContent=s.locked?`Servidor en uso por ${s.lock.owner}. Última señal: ${s.lock.lastHeartbeatAt}. Caduca: ${s.lock.expiresAt}.`:'';
 if(b){
  const labels={completed:'Completado',pending:'Pendiente',failed:'Fallido',unknown:'Sin resultado',disabled:'Desactivado',not_initialized:'Sin partida'};
  const stateLabel=b.stalePending&&b.state==='unknown'?'Sin resultado (marcador vencido)':labels[b.state]||b.state;
  document.querySelector('#backupState').textContent=`Estado: ${stateLabel}`;document.querySelector('#backupState').className=`backup-${b.state}`;
  const pendingVersions=Array.isArray(b.pendingVersions)?b.pendingVersions:[];
  const staleVersions=Array.isArray(b.stalePendingVersions)?b.stalePendingVersions:[];
  document.querySelector('#backupFacts').innerHTML=[['Última versión publicada',b.latestPublishedVersion||'—'],['Última versión respaldada',b.lastCompleted?.version||'—'],['Último backup completado',b.lastCompleted?.completedAt||'—'],['Último exitCode',b.lastAttempt?.exitCode??'—'],['Pendientes',pendingVersions.map(x=>x.version).join(', ')||'Ninguno'],['Marcadores vencidos',staleVersions.map(x=>x.version).join(', ')||'Ninguno'],['Versión actual respaldada',b.latestVersionBackedUp?'Sí':'No']].map(x=>`<div><div class=label>${esc(x[0])}</div><div class=value>${esc(x[1])}</div></div>`).join('');
 }else{
  document.querySelector('#backupState').textContent='Estado: no disponible';document.querySelector('#backupState').className='backup-unknown';document.querySelector('#backupFacts').innerHTML='';
 }
 document.querySelector('#history').innerHTML=h.versions.map(v=>{const id=safeInt(v.version);return `<tr><td>${id}</td><td><code>${esc(v.saveIdentity)}</code></td><td>${esc(v.updatedBy)}</td><td>${esc(v.updatedAt)}</td><td>${esc(v.size)}</td><td><code>${esc(v.sha256)}</code></td><td>${role==='admin'?`<a href=__WEB_API_PREFIX__/history/${id}/download>Descargar</a> <button onclick=restoreV(${id})>Restaurar</button>`:''}</td></tr>`}).join('');
 document.querySelector('#force').hidden=role!=='admin'||!s.locked;if(role==='admin')loadTokens()
}
async function restoreV(v){if(confirm(`¿Restaurar v${v} como nueva versión?`)){await mutate(`__WEB_API_PREFIX__/history/${v}/restore`);load()}}
document.querySelector('#force').onclick=async()=>{const reason=prompt('Motivo del desbloqueo forzado:');if(reason){await mutate('__WEB_API_PREFIX__/admin/force-unlock','POST',{reason});load()}};
async function loadTokens(){document.querySelector('#tokensCard').hidden=false;const j=await fetch('__WEB_API_PREFIX__/admin/tokens').then(r=>r.json());document.querySelector('#tokens').innerHTML=j.tokens.map(t=>{const id=safeInt(t.id);return `<p>#${id} ${esc(t.username)} · ${esc(t.name)} · ${t.revoked_at?'revocado':`<button onclick=revokeT(${id})>Revocar</button>`}</p>`}).join('')}
async function revokeT(id){await mutate(`__WEB_API_PREFIX__/admin/tokens/${id}`,'DELETE');loadTokens()}
document.querySelector('#createToken').onclick=async()=>{const [r,j]=await mutate('__WEB_API_PREFIX__/admin/tokens','POST',{username:tokenUser.value,name:tokenName.value});if(r.ok){newToken.textContent=j.token;loadTokens()}};
load();setInterval(load,30000)
</script></body></html>"""
