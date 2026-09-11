import hashlib
import hmac
import os
import secrets
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from save_sync.domain import SaveSyncDomainError


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class PublicationService:
    def __init__(
        self,
        *,
        storage,
        transaction,
        audit,
        current_version,
        active_lock,
        arm_backup_marker,
        cleanup_canonical_versions,
        post_publish,
        identity_conflict_code,
        identity_conflict_message,
        identity_conflict_details,
        identity_json,
        legacy_palworld,
        managed_hosts,
        iso,
        now,
        max_upload_size,
        max_zip_entries,
        max_uncompressed_size,
        max_compression_ratio,
        logger,
    ):
        self.storage = Path(storage)
        self.transaction = transaction
        self.audit = audit
        self.current_version = current_version
        self.active_lock = active_lock
        self.arm_backup_marker = arm_backup_marker
        self.cleanup_canonical_versions = cleanup_canonical_versions
        self.post_publish = post_publish
        self.identity_conflict_code = identity_conflict_code
        self.identity_conflict_message = identity_conflict_message
        self.identity_conflict_details = identity_conflict_details
        self.identity_json = identity_json
        self.legacy_palworld = legacy_palworld
        self.managed_hosts = managed_hosts
        self.iso = iso
        self.now = now
        self.max_upload_size = max_upload_size
        self.max_zip_entries = max_zip_entries
        self.max_uncompressed_size = max_uncompressed_size
        self.max_compression_ratio = max_compression_ratio
        self.logger = logger

    @staticmethod
    def _limit(value):
        return int(value() if callable(value) else value)

    def validate_zip(self, path):
        if path.suffix.lower() != ".zip":
            raise ValueError("zip_extension")
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > self._limit(self.max_zip_entries):
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
                    if total > self._limit(self.max_uncompressed_size):
                        raise ValueError("zip_uncompressed_too_large")
                    ratio = entry.file_size / max(entry.compress_size, 1)
                    if ratio > self._limit(self.max_compression_ratio):
                        raise ValueError("zip_compression_ratio")
                if total / max(compressed_total, 1) > self._limit(
                    self.max_compression_ratio
                ):
                    raise ValueError("zip_compression_ratio")
                bad = archive.testzip()
                if bad:
                    raise ValueError("zip_corrupt")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
            raise ValueError("zip_invalid") from exc

    def _audit_upload_failure(self, user, *, reason, base_version, save_identity):
        with self.transaction(immediate=True) as db:
            self.audit(
                db,
                "upload_failed",
                user,
                False,
                reason=reason,
                baseVersion=base_version,
                saveIdentity=save_identity,
            )

    def _validate_managed_publication(self, db, user, lock):
        if self.managed_hosts and lock and lock["host_id"] is None:
            self.audit(
                db,
                "upload_failed",
                user,
                False,
                lock["client_id"],
                reason="managed_session_required",
            )
            raise SaveSyncDomainError(
                "managed_session_required",
                "This session predates managed computer authorization and cannot publish.",
                409,
            )
        if not self.managed_hosts or not lock:
            return

        owner_access = db.execute(
            "SELECT u.active user_active,t.id token_id,t.revoked_at token_revoked_at,"
            "t.host_id token_host_id FROM users u "
            "LEFT JOIN api_tokens t ON t.id=? WHERE u.id=?",
            (lock["token_id"], lock["owner_user_id"]),
        ).fetchone()
        if (
            not owner_access
            or owner_access["user_active"] != 1
            or lock["token_id"] is None
            or owner_access["token_id"] is None
            or owner_access["token_revoked_at"] is not None
            or owner_access["token_host_id"] != lock["host_id"]
        ):
            self.audit(
                db,
                "upload_failed",
                user,
                False,
                lock["client_id"],
                reason="access_revoked",
            )
            raise SaveSyncDomainError(
                "access_revoked",
                "This session's user or API token was revoked before publication.",
                409,
            )
        host = db.execute(
            "SELECT active FROM authorized_hosts WHERE id=?", (lock["host_id"],)
        ).fetchone()
        if not host or host["active"] != 1:
            self.audit(
                db,
                "upload_failed",
                user,
                False,
                lock["client_id"],
                reason="host_disabled",
            )
            raise SaveSyncDomainError(
                "host_disabled",
                "This computer was disabled while the session was active.",
                409,
            )

    def publish(
        self,
        user,
        *,
        upload_stream,
        filename,
        session_id,
        base_version,
        claimed_hash,
        save_identity,
    ):
        suffix = Path(filename or "").suffix.lower()
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="upload-", suffix=suffix, dir=self.storage / "temporary"
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        published_final = None

        try:
            hasher = hashlib.sha256()
            size = 0
            with temporary.open("wb") as target:
                while chunk := upload_stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > self._limit(self.max_upload_size):
                        self._audit_upload_failure(
                            user,
                            reason="upload_too_large",
                            base_version=base_version,
                            save_identity=save_identity,
                        )
                        raise SaveSyncDomainError(
                            "upload_too_large",
                            "The file exceeds the configured limit.",
                            413,
                        )
                    hasher.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())

            actual = hasher.hexdigest()
            if not hmac.compare_digest(actual, claimed_hash):
                self._audit_upload_failure(
                    user,
                    reason="sha256_mismatch",
                    base_version=base_version,
                    save_identity=save_identity,
                )
                raise SaveSyncDomainError(
                    "sha256_mismatch",
                    "The SHA-256 digest does not match.",
                    422,
                    {"calculatedSha256": actual},
                )
            try:
                self.validate_zip(temporary)
            except ValueError as exc:
                self._audit_upload_failure(
                    user,
                    reason=str(exc),
                    base_version=base_version,
                    save_identity=save_identity,
                )
                raise SaveSyncDomainError(
                    str(exc), "The ZIP failed the security validations.", 422
                ) from exc

            with self.transaction(immediate=True) as db:
                current = self.current_version(db)
                expected = current["version"] if current else 0
                expected_identity = current["save_identity"] if current else None
                if expected_identity and not hmac.compare_digest(
                    expected_identity, save_identity
                ):
                    details = self.identity_conflict_details(
                        expected_identity, save_identity
                    )
                    self.audit(
                        db,
                        self.identity_conflict_code,
                        user,
                        False,
                        **details,
                    )
                    raise SaveSyncDomainError(
                        self.identity_conflict_code,
                        self.identity_conflict_message,
                        409,
                        details,
                    )
                if base_version != expected:
                    self.audit(
                        db,
                        "version_conflict",
                        user,
                        False,
                        expected=expected,
                        received=base_version,
                        saveIdentity=save_identity,
                        **(
                            {"worldGuid": save_identity}
                            if self.legacy_palworld
                            else {}
                        ),
                    )
                    raise SaveSyncDomainError(
                        "version_conflict",
                        "The remote version has changed.",
                        409,
                        {
                            "expectedBaseVersion": expected,
                            "receivedBaseVersion": base_version,
                        },
                    )

                lock = self.active_lock(db)
                self._validate_managed_publication(db, user, lock)
                same_token = lock and (
                    lock["token_id"] is None
                    or (
                        dict(user).get("token_id") is not None
                        and lock["token_id"] == user["token_id"]
                    )
                )
                if (
                    not lock
                    or lock["owner_user_id"] != user["id"]
                    or not same_token
                    or not hmac.compare_digest(
                        lock["session_hash"], hashlib.sha256(session_id.encode()).hexdigest()
                    )
                ):
                    self.audit(
                        db,
                        "upload_failed",
                        user,
                        False,
                        reason="invalid_session",
                    )
                    raise SaveSyncDomainError(
                        "invalid_session",
                        "The session does not exist, has expired or does not belong to the user.",
                        409,
                    )

                self.audit(
                    db,
                    "upload_started",
                    user,
                    True,
                    lock["client_id"],
                    baseVersion=base_version,
                    size=size,
                )
                if lock["base_version"] != expected:
                    self.audit(
                        db,
                        "version_conflict",
                        user,
                        False,
                        expected=expected,
                        received=base_version,
                        saveIdentity=save_identity,
                        **(
                            {"worldGuid": save_identity}
                            if self.legacy_palworld
                            else {}
                        ),
                    )
                    raise SaveSyncDomainError(
                        "version_conflict",
                        "The remote version has changed.",
                        409,
                        {
                            "expectedBaseVersion": expected,
                            "receivedBaseVersion": base_version,
                        },
                    )

                new_version = expected + 1
                relative = f"backups/save-v{new_version:06d}.zip"
                final = self.storage / relative
                if final.exists():
                    referenced = db.execute(
                        "SELECT 1 FROM versions WHERE path=?", (relative,)
                    ).fetchone()
                    if referenced:
                        raise RuntimeError("version_path_exists")
                    final.unlink()
                os.replace(temporary, final)
                _fsync_directory(final.parent)
                published_final = final
                db.execute(
                    "INSERT INTO versions(version,path,sha256,size,updated_by,updated_at,base_version,save_identity,host_id) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        new_version,
                        relative,
                        actual,
                        size,
                        user["id"],
                        self.iso(self.now()),
                        base_version,
                        save_identity,
                        lock["host_id"],
                    ),
                )
                if lock["host_id"] is not None:
                    db.execute(
                        "UPDATE authorized_hosts SET last_seen_at=?,last_published_at=? WHERE id=?",
                        (
                            self.iso(self.now()),
                            self.iso(self.now()),
                            lock["host_id"],
                        ),
                    )
                db.execute(
                    "INSERT INTO current_save(singleton,version) VALUES(1,?) "
                    "ON CONFLICT(singleton) DO UPDATE SET version=excluded.version",
                    (new_version,),
                )
                self.arm_backup_marker(db, new_version)
                db.execute("DELETE FROM active_lock WHERE singleton=1")
                self.audit(
                    db,
                    "upload_completed",
                    user,
                    True,
                    lock["client_id"],
                    version=new_version,
                    previousVersion=expected,
                    **self.identity_json(save_identity),
                )
                updated_at = db.execute(
                    "SELECT updated_at FROM versions WHERE version=?", (new_version,)
                ).fetchone()[0]

            published_final = None
            try:
                self.cleanup_canonical_versions()
            except Exception:
                self.logger.exception(
                    "Post-publication cleanup failed; the confirmed version is preserved"
                )
            self.post_publish(new_version, relative, save_identity)
            return {
                "ok": True,
                "previousVersion": base_version,
                "version": new_version,
                "sha256": actual,
                "size": size,
                "updatedAt": updated_at,
            }
        except Exception:
            if published_final is not None:
                published_final.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def restore(self, user, version):
        final = None
        temporary = None
        try:
            with self.transaction(immediate=True) as db:
                lock = self.active_lock(db)
                if lock:
                    raise SaveSyncDomainError(
                        "lock_occupied",
                        "Restore is not allowed during an active session.",
                        409,
                        {
                            "owner": lock["owner_label"],
                            "expiresAt": lock["expires_at"],
                        },
                    )
                source_row = db.execute(
                    "SELECT * FROM versions WHERE version=?", (version,)
                ).fetchone()
                source = dict(source_row) if source_row else None
                if not source:
                    raise SaveSyncDomainError(
                        "version_not_found", "Version not found.", 404
                    )
                initial_current = self.current_version(db)
                initial_current_version = (
                    initial_current["version"] if initial_current else 0
                )
                if initial_current and not hmac.compare_digest(
                    initial_current["save_identity"], source["save_identity"]
                ):
                    details = self.identity_conflict_details(
                        initial_current["save_identity"], source["save_identity"]
                    )
                    self.audit(
                        db,
                        self.identity_conflict_code,
                        user,
                        False,
                        **details,
                        operation="backup_restore",
                    )
                    raise SaveSyncDomainError(
                        self.identity_conflict_code,
                        self.identity_conflict_message,
                        409,
                        details,
                    )
                source_path = self.storage / source["path"]

            if not source_path.is_file():
                raise SaveSyncDomainError(
                    "backup_integrity_failed",
                    "The backup is unavailable or failed integrity checks.",
                    503,
                )
            temporary = (
                self.storage / "temporary" / f"restore-{secrets.token_hex(12)}.zip"
            )
            source_hash = hashlib.sha256()
            with source_path.open("rb") as source_stream, temporary.open("wb") as target:
                while chunk := source_stream.read(1024 * 1024):
                    source_hash.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if source_hash.hexdigest() != source["sha256"]:
                raise SaveSyncDomainError(
                    "backup_integrity_failed",
                    "The backup is unavailable or failed integrity checks.",
                    503,
                )

            with self.transaction(immediate=True) as db:
                lock = self.active_lock(db)
                if lock:
                    raise SaveSyncDomainError(
                        "lock_occupied",
                        "A session started while restore was being prepared.",
                        409,
                        {
                            "owner": lock["owner_label"],
                            "expiresAt": lock["expires_at"],
                        },
                    )
                current = self.current_version(db)
                current_number = current["version"] if current else 0
                if current and not hmac.compare_digest(
                    current["save_identity"], source["save_identity"]
                ):
                    details = self.identity_conflict_details(
                        current["save_identity"], source["save_identity"]
                    )
                    self.audit(
                        db,
                        self.identity_conflict_code,
                        user,
                        False,
                        **details,
                        operation="backup_restore",
                    )
                    raise SaveSyncDomainError(
                        self.identity_conflict_code,
                        self.identity_conflict_message,
                        409,
                        details,
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
                    self.audit(
                        db,
                        "version_conflict",
                        user,
                        False,
                        expected=current_number,
                        received=initial_current_version,
                        saveIdentity=current["save_identity"] if current else None,
                        **(
                            {
                                "worldGuid": current["save_identity"]
                                if current
                                else None
                            }
                            if self.legacy_palworld
                            else {}
                        ),
                        operation="backup_restore",
                    )
                    raise SaveSyncDomainError(
                        "version_conflict",
                        "Remote state changed while restore was being prepared.",
                        409,
                        {
                            "expectedBaseVersion": current_number,
                            "receivedBaseVersion": initial_current_version,
                        },
                    )

                new_version = current_number + 1
                relative = f"backups/save-v{new_version:06d}.zip"
                final = self.storage / relative
                if (
                    final.exists()
                    and not db.execute(
                        "SELECT 1 FROM versions WHERE path=?", (relative,)
                    ).fetchone()
                ):
                    final.unlink()
                os.replace(temporary, final)
                _fsync_directory(final.parent)
                now = self.iso(self.now())
                db.execute(
                    "INSERT INTO versions(version,path,sha256,size,updated_by,updated_at,base_version,restored_from_version,save_identity) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        new_version,
                        relative,
                        source["sha256"],
                        source["size"],
                        user["id"],
                        now,
                        current_number,
                        version,
                        source["save_identity"],
                    ),
                )
                db.execute(
                    "INSERT INTO current_save VALUES(1,?) "
                    "ON CONFLICT(singleton) DO UPDATE SET version=excluded.version",
                    (new_version,),
                )
                self.arm_backup_marker(db, new_version)
                self.audit(
                    db,
                    "backup_restored",
                    user,
                    True,
                    restoredFrom=version,
                    version=new_version,
                    **self.identity_json(source["save_identity"]),
                )
        except Exception:
            if final:
                final.unlink(missing_ok=True)
            raise
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

        try:
            self.cleanup_canonical_versions()
        except Exception:
            self.logger.exception(
                "Post-restore cleanup failed; the confirmed version is preserved"
            )
        self.post_publish(new_version, relative, source["save_identity"])
        return {
            "ok": True,
            "version": new_version,
            "restoredFromVersion": version,
            "sha256": source["sha256"],
            "size": source["size"],
            "updatedAt": now,
            "saveIdentity": source["save_identity"],
        }
