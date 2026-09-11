import hashlib
import hmac
import json
import os
import secrets
import shlex
import signal
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, Response, g, jsonify, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from save_sync.admin import register_admin_routes
from save_sync.database import SCHEMA_VERSION as DATABASE_SCHEMA_VERSION
from save_sync.database import bootstrap_database, connect_database
from save_sync.domain import SaveSyncDomainError
from save_sync.game_config import load_game_configuration
from save_sync.identities import identity_for_username as resolve_identity_for_username
from save_sync.identities import load_identities
from save_sync.managed import register_managed_access_routes
from save_sync.panels import register_panel_routes
from save_sync.publications import PublicationService
from save_sync.retention import (
    prune_canonical_versions_locked,
    reconcile_unreferenced_files_locked,
)
from save_sync.sessions import SessionService

SCHEMA_VERSION = DATABASE_SCHEMA_VERSION


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def error(code, message, status, details=None):
    return jsonify(error=code, message=message, details=details or {}), status


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
        raise RuntimeError("SAVE_SYNC_RETENTION_PER_SLOT must be >= 1")
    if int(app.config["SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS"]) < 1:
        raise RuntimeError("SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS must be >= 1")
    game_config = load_game_configuration(app.config)
    game_key = game_config.key
    display_game = game_config.display_name
    identity_field = game_config.identity_field
    identity_label = game_config.identity_label
    legacy_palworld = game_config.legacy_palworld
    managed_hosts = game_config.managed_hosts
    normalize_identity_value = game_config.normalize_identity_value
    app.extensions["save_sync_game"] = game_config.extension_payload()
    identities = load_identities(app.config["SAVE_SYNC_USER_IDENTITIES_JSON"])
    if not app.config.get("TESTING"):
        for required_secret in ("SAVE_SYNC_PROXY_SECRET", "SAVE_SYNC_CSRF_SECRET"):
            value = str(
                app.config.get(required_secret) or os.environ.get(required_secret, "")
            )
            if len(value) < 32 or value.startswith(("REPLACE", "REEMPLAZAR")):
                raise RuntimeError(
                    f"{required_secret} must be configured with at least 32 random characters"
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
        return connect_database(app.config["SAVE_SYNC_DB_PATH"])

    app.extensions["save_sync_connect"] = connect
    bootstrap_database(
        db_path=app.config["SAVE_SYNC_DB_PATH"],
        app_config=app.config,
        identities=identities,
        managed_hosts=managed_hosts,
        normalize_identity_value=normalize_identity_value,
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

    @contextmanager
    def domain_transaction(immediate=False):
        """Commit expected domain rejections just like the former inline routes.

        The legacy route handlers returned HTTP errors from inside their transaction
        blocks, which committed audit rows (and intentional expired-lock cleanup).
        Domain services express those same rejections as exceptions, so catch them
        until the underlying transaction has committed, then re-raise for the HTTP
        layer to translate.
        """
        failure = None
        with transaction(immediate=immediate) as db:
            try:
                yield db
            except SaveSyncDomainError as exc:
                failure = exc
        if failure is not None:
            raise failure

    def identity_for_username(username):
        return resolve_identity_for_username(identities, username)

    def display_from_values(username, persisted=None):
        persisted = str(persisted or "").strip()
        return persisted or identity_for_username(username)["displayName"]

    retention_per_slot = int(app.config["SAVE_SYNC_RETENTION_PER_SLOT"])
    backup_timeout = int(app.config["SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS"])

    def cleanup_canonical_versions():
        """Keeps the latest N versions per slot with best-effort filesystem cleanup.

        A pending_backups row does not expire during cleanup: it is a durable queue and protects
        its ZIP until the external supervisor records success or failure. The
        metadata retention decision is committed before any physical unlink.
        """
        with transaction(immediate=True) as db:
            prune_canonical_versions_locked(
                db,
                retention_per_slot,
                identity_for_username,
            )

        # Second phase after the metadata COMMIT. A new BEGIN IMMEDIATE
        # revalidates every reference before touching the filesystem.
        # If this phase fails, at most one recoverable orphan ZIP remains.
        try:
            with transaction(immediate=True) as db:
                reconcile_unreferenced_files_locked(db, storage, app.logger)
        except Exception:
            app.logger.exception(
                "Metadata retention was committed, but physical "
                "reconciliation failed; a later cleanup will retry it"
            )

    # Recover interrupted cleanups. Pending backups are not purged:
    # they belong to the durable supervisor and survive worker/process restarts.
    cleanup_canonical_versions()

    def terminate_process_group(process, sigterm_timeout=10, sigkill_timeout=10):
        """Inline path used by tests; production delegates to backup-supervisor."""
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
                "The backup process (pid %s) did not exit after SIGKILL",
                process.pid,
            )

    def arm_backup_marker(db, version):
        """Durably queues the version when external backup is enabled.

        The row is created in the same transaction as publication so
        retention can never remove the ZIP before the supervisor
        procese.
        """
        if not str(app.config["SAVE_SYNC_POST_PUBLISH_COMMAND"]).strip():
            return
        db.execute(
            "INSERT OR REPLACE INTO pending_backups(version,started_at) VALUES(?,?)",
            (version, iso(utcnow())),
        )

    def release_backup_marker(version, success, exit_code=0, timed_out=False, reason=None):
        """Inline test support; production completion is handled by backup-supervisor."""
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
                "Could not record the backup result for version %s",
                version,
            )

    def await_backup_result(process, version):
        """Inline test support; production workers do not use it."""
        exit_code = 0
        timed_out = False
        success = False
        try:
            exit_code = process.wait(timeout=backup_timeout)
            success = exit_code == 0
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_group(process, sigterm_timeout=10)
            try:
                exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                exit_code = -1
                app.logger.warning(
                    "External backup for version %s did not exit after SIGKILL",
                    version,
                )
        finally:
            release_backup_marker(version, success, exit_code, timed_out)
            try:
                cleanup_canonical_versions()
            except Exception:
                app.logger.exception(
                    "Post-backup cleanup failed; version %s is preserved",
                    version,
                )
            if not success or timed_out:
                app.logger.warning(
                    "External backup for version %s finished with exit code %s%s",
                    version,
                    exit_code,
                    " (timeout)" if timed_out else "",
                )

    def run_post_publish_hook(version, relative_path, save_identity):
        """Inline executor used only in TESTING.

        In production the worker only creates pending_backups and the sidecar
        save_sync.backup_supervisor executes and supervises the command.
        """
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
            app.logger.exception(
                "The test post-publication hook failed for version %s",
                version,
            )
            release_backup_marker(version, False, reason="hook_launch_failed")
            try:
                cleanup_canonical_versions()
            except Exception:
                app.logger.exception(
                    "Cleanup after hook failure failed; version %s is preserved",
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
            app.logger.exception(
                "Could not start the inline test supervisor for version %s",
                version,
            )
            terminate_process_group(process)
            release_backup_marker(version, False, reason="thread_start_failed")
            try:
                cleanup_canonical_versions()
            except Exception:
                app.logger.exception(
                    "Cleanup after supervisor failure failed; version %s is preserved",
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

    def display_username(username, persisted=None):
        return display_from_values(username, persisted)

    def display_name(user):
        persisted = dict(user).get("display_name")
        return display_username(user["username"], persisted)

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
            return None, error("https_required", "The API requires HTTPS.", 403)
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
                    "SELECT u.*,t.id token_id,t.host_id token_host_id,h.active token_host_active "
                    "FROM api_tokens t JOIN users u ON u.id=t.user_id "
                    "LEFT JOIN authorized_hosts h ON h.id=t.host_id "
                    "WHERE t.token_hash=? AND t.revoked_at IS NULL AND u.active=1",
                    (token_hash,),
                ).fetchone()
                if (
                    managed_hosts
                    and user
                    and user["token_host_id"] is not None
                    and user["token_host_active"] != 1
                ):
                    return None, error(
                        "host_disabled",
                        "This computer is disabled for Save Sync.",
                        403,
                    )
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
                        f"The authenticated user is not authorized for {display_game}.",
                        403,
                    )
                if user and request.method not in {"GET", "HEAD", "OPTIONS"}:
                    expected = csrf_value(user["username"])
                    supplied = request.headers.get("X-CSRF-Token", "")
                    if not expected or not hmac.compare_digest(expected, supplied):
                        return None, error(
                            "csrf_failed", "CSRF token missing or invalid.", 403
                        )
            if not user:
                return None, error(
                    "authentication_required", "Valid authentication is required.", 401
                )
            if (
                managed_hosts
                and
                require_admin
                and dict(user).get("token_host_id") is not None
            ):
                return None, error(
                    "forbidden",
                    "Computer-bound API tokens cannot perform administrative operations.",
                    403,
                )
            if require_admin and user["role"] != "admin":
                return None, error(
                    "forbidden", "Administrative permissions are required.", 403
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
                return None, error("rate_limit_exceeded", "Too many requests.", 429)
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

    session_service = SessionService(
        transaction=domain_transaction,
        audit=audit,
        current_version=current_version,
        digest=digest,
        iso=iso,
        parse_iso=parse_iso,
        now=lambda: utcnow(),
        display_name=display_name,
        managed_hosts=managed_hosts,
        lock_ttl_seconds=int(app.config["SAVE_SYNC_LOCK_TTL_SECONDS"]),
    )

    def domain_error_response(exc):
        return error(exc.code, exc.message, exc.status, exc.details)

    def backup_status_snapshot(db):
        """Summarizes observable hook state without assuming restic is healthy."""
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
                is_stale = True
            (stale_pending if is_stale else pending).append(item)

        last_attempt = None
        last_completed = None
        current_attempt = None
        rows = db.execute(
            "SELECT event,at,success,details FROM audit "
            "WHERE event IN ('backup_hook_completed','backup_hook_failed') "
            "ORDER BY id DESC"
        )
        for row in rows:
            try:
                details = json.loads(row["details"])
                version = int(details["version"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            attempt = {
                "version": version,
                "completedAt": row["at"],
                "success": bool(row["success"]),
                "exitCode": details.get("exitCode"),
                "timedOut": bool(details.get("timedOut", False)),
                "reason": details.get("reason"),
            }
            if last_attempt is None:
                last_attempt = attempt
            if last_completed is None and attempt["success"]:
                last_completed = attempt
            if current_attempt is None and version == latest_version:
                current_attempt = attempt
            if (
                last_attempt is not None
                and last_completed is not None
                and (current_attempt is not None or not current)
            ):
                break

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

    active_lock = session_service.active_lock
    lock_public = session_service.public_lock

    def post_publish(version, relative_path, save_identity):
        if app.config.get("TESTING"):
            run_post_publish_hook(version, relative_path, save_identity)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc):
        return error(
            "upload_too_large",
            "The file exceeds the configured limit.",
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
                "Internal error; no version was published.",
                500,
            )
        return Response("Internal error", 500, content_type="text/plain; charset=utf-8")

    @app.errorhandler(404)
    def not_found(_exc):
        if request.path.startswith(
            (f"/api/games/{game_key}", f"/games/{game_key}/api")
        ) or (legacy_palworld and request.path.startswith(("/api/palworld", "/palworld/api"))):
            return error("not_found", "Resource not found.", 404)
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
            return error("storage_unavailable", "Database unavailable.", 503)

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
        "The ZIP belongs to a different Palworld world."
        if legacy_palworld
        else f"The ZIP belongs to a different save for {display_game}."
    )

    publication_service = PublicationService(
        storage=storage,
        transaction=domain_transaction,
        audit=audit,
        current_version=current_version,
        active_lock=active_lock,
        arm_backup_marker=arm_backup_marker,
        cleanup_canonical_versions=cleanup_canonical_versions,
        post_publish=post_publish,
        identity_conflict_code=identity_conflict_code,
        identity_conflict_message=identity_conflict_message,
        identity_conflict_details=identity_conflict_details,
        identity_json=identity_json,
        legacy_palworld=legacy_palworld,
        managed_hosts=managed_hosts,
        iso=iso,
        now=lambda: utcnow(),
        max_upload_size=lambda: app.config["SAVE_SYNC_MAX_UPLOAD_SIZE"],
        max_zip_entries=lambda: app.config["SAVE_SYNC_MAX_ZIP_ENTRIES"],
        max_uncompressed_size=lambda: app.config["SAVE_SYNC_MAX_UNCOMPRESSED_SIZE"],
        max_compression_ratio=lambda: app.config["SAVE_SYNC_MAX_COMPRESSION_RATIO"],
        logger=app.logger,
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
            author = (
                db.execute(
                    "SELECT u.username,u.display_name,h.client_id,h.name host_name "
                    "FROM users u LEFT JOIN authorized_hosts h ON h.id=? WHERE u.id=?",
                    (version["host_id"], version["updated_by"]),
                ).fetchone()
                if version
                else None
            )
            result = {
                "gameKey": game_key,
                "game": display_game,
                "identityField": identity_field,
                "initialized": bool(version),
                "version": version["version"] if version else 0,
                "sha256": version["sha256"] if version else None,
                "size": version["size"] if version else 0,
                "updatedAt": version["updated_at"] if version else None,
                "updatedBy": display_username(author["username"], author["display_name"])
                if author
                else None,
                "locked": bool(lock),
                "lock": lock_public(lock) if lock else None,
            }
            if managed_hosts:
                result.update(
                    updatedClientId=author["client_id"] if author else None,
                    updatedHostName=author["host_name"] if author else None,
                )
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
        session_id = secrets.token_urlsafe(48)
        try:
            result = session_service.acquire(
                g.save_sync_user,
                owner=data.get("owner"),
                client_id=data.get("clientId"),
                session_id=session_id,
            )
        except SaveSyncDomainError as exc:
            return domain_error_response(exc)
        lock_response = {
            "sessionId": result["sessionId"],
            "baseVersion": result["baseVersion"],
            "expiresAt": result["expiresAt"],
            "gameKey": game_key,
        }
        lock_response.update(identity_json(result["saveIdentity"]))
        return jsonify(lock_response), 201

    def session_action(event, delete=False):
        data = request.get_json(silent=True) or {}
        try:
            result = session_service.action(
                g.save_sync_user,
                session_id=data.get("sessionId"),
                event=event,
                delete=delete,
            )
        except SaveSyncDomainError as exc:
            return domain_error_response(exc)
        return jsonify(ok=True, **result)

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
                    "save_not_initialized", "There is no remote save yet.", 404
                )
            path = storage / row["path"]
            audit(db, "download", g.save_sync_user, True, version=row["version"])
        if not path.is_file():
            return error(
                "storage_unavailable", "The recorded version is not available.", 503
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
                f"file, sessionId, baseVersion, sha256 and {identity_field} are required.",
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
                f"{identity_field} does not match the configured format.",
                400,
                details,
            )
        try:
            result = publication_service.publish(
                g.save_sync_user,
                upload_stream=upload_file.stream,
                filename=upload_file.filename,
                session_id=sid,
                base_version=base,
                claimed_hash=claimed_hash,
                save_identity=save_identity,
            )
        except SaveSyncDomainError as exc:
            return domain_error_response(exc)
        result.update(gameKey=game_key)
        result.update(identity_json(save_identity))
        return jsonify(result), 201

    @routes("/history", methods=["GET"])
    @secured()
    def history():
        with transaction() as db:
            rows = db.execute(
                "SELECT v.*,u.username,u.display_name,h.client_id,h.name host_name "
                "FROM versions v JOIN users u ON u.id=v.updated_by "
                "LEFT JOIN authorized_hosts h ON h.id=v.host_id ORDER BY version DESC"
            ).fetchall()
        versions = []
        for r in rows:
            item = {
                "version": r["version"],
                "updatedBy": display_username(r["username"], r["display_name"]),
                "updatedAt": r["updated_at"],
                "size": r["size"],
                "sha256": r["sha256"],
                "baseVersion": r["base_version"],
                "restoredFromVersion": r["restored_from_version"],
            }
            if managed_hosts:
                item.update(clientId=r["client_id"], hostName=r["host_name"])
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
                return error("version_not_found", "Version not found.", 404)
            audit(db, "backup_download", g.save_sync_user, True, version=version)
        path = storage / row["path"]
        if not path.is_file():
            return error(
                "storage_unavailable", "The recorded version is not available.", 503
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
        try:
            result = publication_service.restore(g.save_sync_user, version)
        except SaveSyncDomainError as exc:
            return domain_error_response(exc)
        result.update(gameKey=game_key)
        result.update(identity_json(result["saveIdentity"]))
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
                return error("version_not_found", "Version not found.", 404)
            if version == current["version"]:
                return error(
                    "version_current",
                    "The current version cannot be deleted.",
                    409,
                )
            pending = db.execute(
                "SELECT 1 FROM pending_backups WHERE version=?", (version,)
            ).fetchone()
            if pending:
                return error(
                    "backup_in_progress",
                    "The version has an external backup in progress.",
                    409,
                    {"version": version},
                )
            db.execute("DELETE FROM versions WHERE version=?", (version,))
            audit(db, "backup_deleted", g.save_sync_user, True, version=version)
        (storage / row["path"]).unlink(missing_ok=True)
        return jsonify(ok=True)

    if managed_hosts:
        register_managed_access_routes(
            routes=routes,
            secured=secured,
            transaction=transaction,
            audit=audit,
            error=error,
            display_username=display_username,
            iso=iso,
            utcnow=utcnow,
        )

    register_admin_routes(
        routes=routes,
        secured=secured,
        transaction=transaction,
        audit=audit,
        error=error,
        active_lock=active_lock,
        managed_hosts=managed_hosts,
        digest=digest,
        iso=iso,
        utcnow=utcnow,
        token_factory=lambda: "pws_" + secrets.token_urlsafe(36),
    )

    register_panel_routes(
        app=app,
        connect=connect,
        web_auth=web_auth,
        csrf_value=csrf_value,
        game_key=game_key,
        display_game=display_game,
        identity_label=identity_label,
        managed_hosts=managed_hosts,
        legacy_palworld=legacy_palworld,
    )

    return app
