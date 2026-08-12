import fcntl
import json
import logging
import os
import shlex
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from save_sync.retention import cleanup_canonical_versions_locked


LOGGER = logging.getLogger("save-sync-backup-supervisor")


def utc_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect_database(db_path):
    db = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    return db


def load_identities(raw):
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("SAVE_SYNC_USER_IDENTITIES_JSON no es JSON válido") from exc
    if not isinstance(value, dict):
        raise RuntimeError("SAVE_SYNC_USER_IDENTITIES_JSON debe ser un objeto JSON")
    result = {}
    for username, profile in value.items():
        if not isinstance(profile, dict):
            raise RuntimeError(f"Perfil de identidad inválido para {username}")
        display = str(profile.get("displayName", "")).strip()
        slot = str(profile.get("slot", "")).strip()
        if not str(username).strip() or not display or not slot:
            raise RuntimeError(
                "Cada identidad necesita username, displayName y slot no vacíos"
            )
        result[str(username).casefold()] = {"displayName": display, "slot": slot}
    return result


class BackupSupervisor:
    def __init__(
        self,
        *,
        storage_path,
        db_path,
        command,
        timeout_seconds=1800,
        poll_seconds=1.0,
        retention_per_slot=1,
        identities=None,
        popen=subprocess.Popen,
        monotonic=time.monotonic,
        sleep=time.sleep,
        logger=LOGGER,
    ):
        self.storage = Path(storage_path).resolve()
        self.db_path = str(Path(db_path).resolve())
        self.command = str(command or "").strip()
        self.timeout_seconds = int(timeout_seconds)
        self.poll_seconds = float(poll_seconds)
        self.retention_per_slot = int(retention_per_slot)
        self.identities = identities or {}
        self.popen = popen
        self.monotonic = monotonic
        self.sleep = sleep
        self.logger = logger
        self.stop_requested = False
        self.current_process = None
        self._lock_descriptor = None
        self.heartbeat_path = self.storage / "temporary" / "backup-supervisor.heartbeat"
        if self.timeout_seconds < 1:
            raise RuntimeError("SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS debe ser >= 1")
        if self.poll_seconds <= 0:
            raise RuntimeError("SAVE_SYNC_BACKUP_POLL_SECONDS debe ser > 0")
        if self.retention_per_slot < 1:
            raise RuntimeError("SAVE_SYNC_RETENTION_PER_SLOT debe ser >= 1")

    @classmethod
    def from_environment(cls):
        storage = os.environ.get("SAVE_SYNC_STORAGE_PATH", "/data/save-sync")
        db_path = os.environ.get(
            "SAVE_SYNC_DB_PATH", str(Path(storage) / "save-sync.sqlite3")
        )
        identities = load_identities(
            os.environ.get(
                "SAVE_SYNC_USER_IDENTITIES_JSON",
                '{"admin":{"displayName":"Host A","slot":"host-a"},'
                '"player":{"displayName":"Host B","slot":"host-b"}}',
            )
        )
        return cls(
            storage_path=storage,
            db_path=db_path,
            command=os.environ.get("SAVE_SYNC_POST_PUBLISH_COMMAND", ""),
            timeout_seconds=int(
                os.environ.get("SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS", "1800")
            ),
            poll_seconds=float(os.environ.get("SAVE_SYNC_BACKUP_POLL_SECONDS", "1")),
            retention_per_slot=int(os.environ.get("SAVE_SYNC_RETENTION_PER_SLOT", "1")),
            identities=identities,
        )

    def identity_for_username(self, username):
        return self.identities.get(
            username.casefold(),
            {"displayName": username, "slot": username.casefold()},
        )

    def connect(self):
        return connect_database(self.db_path)

    def schema_ready(self):
        try:
            with self.connect() as db:
                names = {
                    row[0]
                    for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name IN ('versions','users','audit','pending_backups')"
                    )
                }
            return names == {"versions", "users", "audit", "pending_backups"}
        except sqlite3.Error:
            return False

    def touch_heartbeat(self):
        self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_path.touch()

    def acquire_singleton_lock(self):
        lock_path = self.storage / "backup-supervisor.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        self._lock_descriptor = descriptor

    def release_singleton_lock(self):
        if self._lock_descriptor is None:
            return
        try:
            fcntl.flock(self._lock_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self._lock_descriptor)
            self._lock_descriptor = None

    def request_stop(self, *_args):
        self.stop_requested = True

    def install_signal_handlers(self):
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)

    def audit(self, db, event, success, **details):
        db.execute(
            "INSERT INTO audit(event,user_id,at,success,client_id,details) "
            "VALUES(?,?,?,?,?,?)",
            (
                event,
                None,
                utc_iso(),
                int(success),
                None,
                json.dumps(details, separators=(",", ":")),
            ),
        )

    def next_job(self):
        with self.connect() as db:
            return db.execute(
                "SELECT pb.version,pb.started_at,v.path,v.save_identity,u.username "
                "FROM pending_backups pb "
                "JOIN versions v ON v.version=pb.version "
                "JOIN users u ON u.id=v.updated_by "
                "ORDER BY pb.started_at,pb.version LIMIT 1"
            ).fetchone()

    def mark_attempt_started(self, job):
        started_at = utc_iso()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                current = db.execute(
                    "SELECT 1 FROM pending_backups WHERE version=?", (job["version"],)
                ).fetchone()
                if not current:
                    db.rollback()
                    return False
                db.execute(
                    "UPDATE pending_backups SET started_at=? WHERE version=?",
                    (started_at, job["version"]),
                )
                self.audit(
                    db,
                    "backup_hook_started",
                    True,
                    version=job["version"],
                    queuedAt=job["started_at"],
                    startedAt=started_at,
                )
                db.commit()
                return True
            except Exception:
                db.rollback()
                raise

    def finalize_job(self, job, *, success, exit_code=0, timed_out=False, reason=None):
        details = {
            "version": job["version"],
            "exitCode": exit_code,
            "timedOut": 1 if timed_out else 0,
        }
        if reason:
            details["reason"] = reason
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                # DELETE + auditoría + retención forman una sola decisión. Si
                # SQLite falla, rollback conserva el marcador y el trabajo se
                # reintentará (semántica at-least-once, nunca pérdida silenciosa).
                db.execute(
                    "DELETE FROM pending_backups WHERE version=?", (job["version"],)
                )
                self.audit(
                    db,
                    "backup_hook_completed" if success else "backup_hook_failed",
                    success,
                    **details,
                )
                cleanup_canonical_versions_locked(
                    db,
                    self.storage,
                    self.retention_per_slot,
                    self.identity_for_username,
                    self.logger,
                )
                db.commit()
            except Exception:
                db.rollback()
                raise

    def terminate_process_group(self, process, sigterm_timeout=10, sigkill_timeout=10):
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
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=sigkill_timeout)
        except subprocess.TimeoutExpired:
            self.logger.warning(
                "El proceso de backup (pid %s) no terminó tras SIGKILL", process.pid
            )

    def wait_for_process(self, process):
        deadline = self.monotonic() + self.timeout_seconds
        while True:
            self.touch_heartbeat()
            if self.stop_requested:
                self.terminate_process_group(process)
                return None, False, True
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                self.terminate_process_group(process)
                try:
                    exit_code = process.wait(timeout=0)
                except subprocess.TimeoutExpired:
                    exit_code = -1
                return exit_code, True, False
            try:
                return process.wait(timeout=min(1.0, remaining)), False, False
            except subprocess.TimeoutExpired:
                continue

    def run_once(self):
        if not self.schema_ready():
            return False
        job = self.next_job()
        if job is None:
            return False
        if not self.command:
            self.logger.warning(
                "Hay un backup pendiente (v%s) pero SAVE_SYNC_POST_PUBLISH_COMMAND está vacío",
                job["version"],
            )
            return False
        if not self.mark_attempt_started(job):
            return True

        env = os.environ.copy()
        env.update(
            {
                "SAVE_SYNC_PUBLISHED_VERSION": str(job["version"]),
                "SAVE_SYNC_PUBLISHED_PATH": str(self.storage / job["path"]),
                "SAVE_SYNC_PUBLISHED_IDENTITY": job["save_identity"],
                "SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS": str(self.timeout_seconds),
            }
        )
        try:
            argv = shlex.split(self.command)
            if not argv:
                raise ValueError("backup command vacío tras parseo")
            process = self.popen(
                argv,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            self.current_process = process
        except Exception:
            self.logger.exception(
                "No se pudo lanzar el backup externo de la versión %s", job["version"]
            )
            self.finalize_job(
                job,
                success=False,
                exit_code=-1,
                reason="hook_launch_failed",
            )
            return True

        try:
            exit_code, timed_out, interrupted = self.wait_for_process(process)
        finally:
            self.current_process = None
        if interrupted:
            # Reinicio controlado del supervisor: el proceso hijo ya fue
            # terminado, pero el marcador se conserva para reintentar al volver.
            self.logger.info(
                "Backup v%s interrumpido por parada del supervisor; queda pendiente",
                job["version"],
            )
            return True

        success = exit_code == 0 and not timed_out
        self.finalize_job(
            job,
            success=success,
            exit_code=exit_code,
            timed_out=timed_out,
        )
        if not success:
            self.logger.warning(
                "Backup externo v%s terminó con exit code %s%s",
                job["version"],
                exit_code,
                " (timeout)" if timed_out else "",
            )
        return True

    def run_forever(self):
        self.acquire_singleton_lock()
        try:
            while not self.stop_requested and not self.schema_ready():
                self.sleep(min(self.poll_seconds, 1.0))
            while not self.stop_requested:
                self.touch_heartbeat()
                try:
                    worked = self.run_once()
                except Exception:
                    # Un fallo de auditoría/SQLite no debe destruir el único
                    # supervisor. El marcador queda intacto por rollback y se
                    # reintentará en la siguiente iteración.
                    self.logger.exception("Fallo del supervisor; se reintentará")
                    worked = False
                if not worked:
                    self.sleep(self.poll_seconds)
        finally:
            if self.current_process is not None:
                self.terminate_process_group(self.current_process)
            self.release_singleton_lock()


def healthcheck():
    supervisor = BackupSupervisor.from_environment()
    try:
        age = time.time() - supervisor.heartbeat_path.stat().st_mtime
        if age > max(10.0, supervisor.poll_seconds * 5):
            return False
        return supervisor.schema_ready()
    except (OSError, RuntimeError, ValueError):
        return False


def main():
    logging.basicConfig(
        level=os.environ.get("SAVE_SYNC_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if len(sys.argv) > 1 and sys.argv[1] == "--healthcheck":
        raise SystemExit(0 if healthcheck() else 1)
    supervisor = BackupSupervisor.from_environment()
    supervisor.install_signal_handlers()
    supervisor.run_forever()


if __name__ == "__main__":
    main()
