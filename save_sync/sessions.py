import hmac
from datetime import timedelta

from save_sync.domain import SaveSyncDomainError


class SessionService:
    def __init__(
        self,
        *,
        transaction,
        audit,
        current_version,
        digest,
        iso,
        parse_iso,
        now,
        display_name,
        managed_hosts,
        lock_ttl_seconds,
    ):
        self.transaction = transaction
        self.audit = audit
        self.current_version = current_version
        self.digest = digest
        self.iso = iso
        self.parse_iso = parse_iso
        self.now = now
        self.display_name = display_name
        self.managed_hosts = managed_hosts
        self.lock_ttl_seconds = int(lock_ttl_seconds)

    def current_managed_token(self, db, user):
        """Revalidate managed access inside the caller's transaction."""
        if not self.managed_hosts:
            return None
        token_id = dict(user).get("token_id")
        if token_id is None:
            raise SaveSyncDomainError(
                "host_token_required",
                "This game requires an API token bound to an authorized computer.",
                403,
            )
        access = db.execute(
            "SELECT u.active user_active,t.id token_id,t.revoked_at token_revoked_at,"
            "t.host_id token_host_id FROM users u "
            "LEFT JOIN api_tokens t ON t.id=? AND t.user_id=u.id WHERE u.id=?",
            (token_id, user["id"]),
        ).fetchone()
        if (
            not access
            or access["user_active"] != 1
            or access["token_id"] is None
            or access["token_revoked_at"] is not None
        ):
            raise SaveSyncDomainError(
                "access_revoked",
                "This user's access or API token was revoked.",
                403,
            )
        if access["token_host_id"] is None:
            raise SaveSyncDomainError(
                "host_token_required",
                "This game requires an API token bound to an authorized computer.",
                403,
            )
        return access

    def resolve_authorized_host(self, db, user, client_id):
        if not self.managed_hosts:
            return None
        access = self.current_managed_token(db, user)
        host = db.execute(
            "SELECT * FROM authorized_hosts WHERE id=? AND user_id=? AND client_id=?",
            (access["token_host_id"], user["id"], client_id),
        ).fetchone()
        if not host:
            raise SaveSyncDomainError(
                "token_host_mismatch",
                "This API token belongs to a different authorized computer.",
                403,
            )
        if host["active"] != 1:
            raise SaveSyncDomainError(
                "host_disabled", "This computer is disabled for Save Sync.", 403
            )
        return host

    def active_lock(self, db, clear_expired=True):
        row = db.execute(
            "SELECT l.*,u.username,h.name host_name FROM active_lock l "
            "JOIN users u ON u.id=l.owner_user_id "
            "LEFT JOIN authorized_hosts h ON h.id=l.host_id WHERE singleton=1"
        ).fetchone()
        if row and self.parse_iso(row["expires_at"]) <= self.now():
            if clear_expired:
                db.execute("DELETE FROM active_lock WHERE singleton=1")
                self.audit(
                    db,
                    "lock_expired",
                    success=True,
                    client_id=row["client_id"],
                    owner=row["owner_label"],
                )
            return None
        return row

    def public_lock(self, row):
        result = {
            "owner": row["owner_label"],
            "createdAt": row["created_at"],
            "lastHeartbeatAt": row["last_heartbeat_at"],
            "expiresAt": row["expires_at"],
        }
        if self.managed_hosts:
            result.update(clientId=row["client_id"], hostName=row["host_name"])
        return result

    def acquire(self, user, *, owner, client_id, session_id):
        owner = str(owner or "").strip()
        client_id = str(client_id or "").strip()
        if not owner or not client_id or len(owner) > 100 or len(client_id) > 200:
            raise SaveSyncDomainError(
                "invalid_request", "owner and clientId are required.", 400
            )
        canonical_owner = self.display_name(user)
        if owner.casefold() != canonical_owner.casefold():
            raise SaveSyncDomainError(
                "owner_mismatch",
                "owner does not match the authenticated user.",
                403,
                {"expectedOwner": canonical_owner},
            )

        now = self.now()
        expires = now + timedelta(seconds=self.lock_ttl_seconds)
        with self.transaction(immediate=True) as db:
            try:
                host = self.resolve_authorized_host(db, user, client_id)
            except SaveSyncDomainError as exc:
                self.audit(
                    db,
                    "lock_rejected",
                    user,
                    False,
                    client_id,
                    reason=exc.code,
                )
                raise
            existing = self.active_lock(db)
            if existing:
                self.audit(
                    db,
                    "lock_rejected",
                    user,
                    False,
                    client_id,
                    owner=existing["owner_label"],
                    expiresAt=existing["expires_at"],
                )
                raise SaveSyncDomainError(
                    "lock_occupied",
                    "The save is currently in use.",
                    409,
                    {
                        "owner": existing["owner_label"],
                        "expiresAt": existing["expires_at"],
                    },
                )
            version = self.current_version(db)
            base = version["version"] if version else 0
            db.execute(
                "INSERT INTO active_lock(singleton,session_hash,owner_user_id,token_id,owner_label,client_id,base_version,created_at,last_heartbeat_at,expires_at,host_id) VALUES(1,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.digest(session_id),
                    user["id"],
                    dict(user).get("token_id"),
                    canonical_owner,
                    client_id,
                    base,
                    self.iso(now),
                    self.iso(now),
                    self.iso(expires),
                    host["id"] if host else None,
                ),
            )
            if host:
                db.execute(
                    "UPDATE authorized_hosts SET last_seen_at=? WHERE id=?",
                    (self.iso(now), host["id"]),
                )
            self.audit(db, "lock_acquired", user, True, client_id, baseVersion=base)

        return {
            "sessionId": session_id,
            "baseVersion": base,
            "expiresAt": self.iso(expires),
            "saveIdentity": version["save_identity"] if version else None,
        }

    def action(self, user, *, session_id, event, delete=False):
        session_id = str(session_id or "")
        if not session_id:
            raise SaveSyncDomainError(
                "invalid_request", "sessionId is required.", 400
            )
        now = self.now()
        with self.transaction(immediate=True) as db:
            raw = db.execute("SELECT * FROM active_lock WHERE singleton=1").fetchone()
            if (
                raw
                and self.parse_iso(raw["expires_at"]) <= now
                and hmac.compare_digest(raw["session_hash"], self.digest(session_id))
            ):
                db.execute("DELETE FROM active_lock WHERE singleton=1")
                self.audit(db, event, user, False, reason="lock_expired")
                raise SaveSyncDomainError(
                    "lock_expired", "The lock has expired.", 409
                )

            row = self.active_lock(db)
            managed_access = None
            if self.managed_hosts:
                try:
                    managed_access = self.current_managed_token(db, user)
                except SaveSyncDomainError as exc:
                    self.audit(
                        db,
                        event,
                        user,
                        False,
                        row["client_id"] if row else None,
                        reason=exc.code,
                    )
                    raise

            if self.managed_hosts and row:
                if row["host_id"] is None:
                    self.audit(
                        db,
                        event,
                        user,
                        False,
                        row["client_id"],
                        reason="managed_session_required",
                    )
                    raise SaveSyncDomainError(
                        "managed_session_required",
                        "This session predates managed computer authorization and cannot continue.",
                        409,
                    )
                if row["host_id"] != managed_access["token_host_id"]:
                    self.audit(
                        db,
                        event,
                        user,
                        False,
                        row["client_id"],
                        reason="token_host_mismatch",
                    )
                    raise SaveSyncDomainError(
                        "token_host_mismatch",
                        "This API token belongs to a different authorized computer.",
                        403,
                    )
                host = db.execute(
                    "SELECT active FROM authorized_hosts WHERE id=?",
                    (row["host_id"],),
                ).fetchone()
                if not host or host["active"] != 1:
                    self.audit(
                        db,
                        event,
                        user,
                        False,
                        row["client_id"],
                        reason="host_disabled",
                    )
                    raise SaveSyncDomainError(
                        "host_disabled",
                        "This computer was disabled while the session was active.",
                        409,
                    )

            same_token = row and (
                row["token_id"] is None
                or (
                    dict(user).get("token_id") is not None
                    and row["token_id"] == user["token_id"]
                )
            )
            if (
                not row
                or not hmac.compare_digest(
                    row["session_hash"], self.digest(session_id)
                )
                or row["owner_user_id"] != user["id"]
                or not same_token
            ):
                self.audit(db, event, user, False, reason="invalid_session")
                raise SaveSyncDomainError(
                    "invalid_session",
                    "The session does not exist, has expired or does not belong to the user.",
                    409,
                )

            if delete:
                db.execute("DELETE FROM active_lock WHERE singleton=1")
                expires = None
            else:
                expires = now + timedelta(seconds=self.lock_ttl_seconds)
                db.execute(
                    "UPDATE active_lock SET last_heartbeat_at=?,expires_at=? WHERE singleton=1",
                    (self.iso(now), self.iso(expires)),
                )
            self.audit(db, event, user, True, row["client_id"])
            if row["host_id"] is not None:
                db.execute(
                    "UPDATE authorized_hosts SET last_seen_at=? WHERE id=?",
                    (self.iso(now), row["host_id"]),
                )

        return {"expiresAt": self.iso(expires)} if expires else {}
