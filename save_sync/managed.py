import ipaddress
import sqlite3

from flask import g, jsonify, request

# Fail-closed default: only loopback is trusted out of the box. Deployments
# behind Docker/Traefik/Tailscale must set SAVE_SYNC_TRUSTED_PROXY_CIDRS to
# the real proxy ranges (e.g. the Traefik network CIDR); anything else makes
# the direct peer the recorded IP and X-Forwarded-For is ignored.
DEFAULT_TRUSTED_PROXY_CIDRS = ("127.0.0.0/8", "::1/128")


def _as_cidrs(value):
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    else:
        parts = list(value)
    return [ipaddress.ip_network(part) for part in parts]


def parse_trusted_proxy_cidrs(value):
    """Validate the proxy CIDR setting once at startup; fail at deploy time."""
    try:
        networks = _as_cidrs(value)
    except ValueError as exc:
        raise RuntimeError(
            f"SAVE_SYNC_TRUSTED_PROXY_CIDRS is not a valid comma-separated CIDR list: {exc}"
        ) from exc
    if not networks:
        raise RuntimeError("SAVE_SYNC_TRUSTED_PROXY_CIDRS must list at least one CIDR")
    return networks


def extract_client_ip(request, trusted_cidrs=None):
    """Best-effort public client IP behind a reverse proxy.

    Never trusts X-Forwarded-For blindly: the direct TCP peer (recovered
    from before ProxyFix rewrote it) must fall inside the explicitly
    configured proxy CIDRs, otherwise the peer itself is returned and
    headers are ignored. With a trusted peer, X-Forwarded-For is walked
    right-to-left skipping trusted proxies, so client-supplied spoofed
    entries on the left and chained proxies on the right are both handled.
    Returns "" when nothing parseable exists.
    """
    networks = _as_cidrs(
        trusted_cidrs if trusted_cidrs else DEFAULT_TRUSTED_PROXY_CIDRS
    )
    orig = request.environ.get("werkzeug.proxy_fix.orig") or {}
    peer = str(orig.get("REMOTE_ADDR") or request.environ.get("REMOTE_ADDR") or "")
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return ""
    if not any(peer_ip in net for net in networks):
        return peer
    chain = [
        part.strip()
        for part in request.headers.get("X-Forwarded-For", "").split(",")
        if part.strip()
    ]
    for raw in reversed(chain):
        try:
            candidate = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if not any(candidate in net for net in networks):
            return raw
    return chain[-1] if chain else peer


def register_managed_access_routes(
    *,
    routes,
    secured,
    transaction,
    audit,
    error,
    display_username,
    iso,
    utcnow,
):
    @routes("/admin/users", methods=["GET", "POST"])
    @secured(admin=True)
    def admin_users():
        if request.method == "GET":
            with transaction() as db:
                rows = db.execute(
                    "SELECT u.id,u.username,u.role,u.active,u.display_name,u.slot,"
                    "COUNT(h.id) host_count,COALESCE(SUM(CASE WHEN h.active=1 THEN 1 ELSE 0 END),0) active_host_count,"
                    "MAX(h.last_seen_at) last_seen_at,MAX(h.last_published_at) last_published_at "
                    "FROM users u LEFT JOIN authorized_hosts h ON h.user_id=u.id "
                    "GROUP BY u.id ORDER BY u.username COLLATE NOCASE"
                ).fetchall()
            return jsonify(
                users=[
                    {
                        "id": row["id"],
                        "username": row["username"],
                        "displayName": display_username(
                            row["username"], row["display_name"]
                        ),
                        "slot": row["slot"] or row["username"].casefold(),
                        "role": row["role"],
                        "active": bool(row["active"]),
                        "hostCount": row["host_count"],
                        "activeHostCount": row["active_host_count"],
                        "lastSeenAt": row["last_seen_at"],
                        "lastPublishedAt": row["last_published_at"],
                    }
                    for row in rows
                ]
            )

        data = request.get_json(silent=True) or {}
        username = str(data.get("username", "")).strip()
        display = str(data.get("displayName", "")).strip()
        slot = str(data.get("slot", "")).strip()
        role = str(data.get("role", "player")).strip().lower()
        if (
            not username
            or len(username) > 100
            or not display
            or len(display) > 100
            or not slot
            or len(slot) > 100
            or role not in {"admin", "player"}
        ):
            return error(
                "invalid_request",
                "username, displayName and slot are required and role must be admin or player.",
                400,
            )
        with transaction(immediate=True) as db:
            if db.execute(
                "SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (username,)
            ).fetchone():
                return error("user_exists", "That user already exists.", 409)
            cursor = db.execute(
                "INSERT INTO users(username,role,active,display_name,slot) VALUES(?,?,1,?,?)",
                (username, role, display, slot),
            )
            audit(
                db,
                "user_created",
                g.save_sync_user,
                True,
                targetUserId=cursor.lastrowid,
                username=username,
                role=role,
            )
        return jsonify(
            id=cursor.lastrowid,
            username=username,
            displayName=display,
            slot=slot,
            role=role,
            active=True,
        ), 201

    @routes("/admin/users/<int:user_id>", methods=["PATCH"])
    @secured(admin=True)
    def update_user(user_id):
        data = request.get_json(silent=True) or {}
        allowed = {"displayName", "slot", "role", "active"}
        if not data or any(key not in allowed for key in data):
            return error("invalid_request", "No supported user fields were supplied.", 400)
        updates = {}
        if "displayName" in data:
            value = str(data["displayName"]).strip()
            if not value or len(value) > 100:
                return error("invalid_request", "displayName must be 1-100 characters.", 400)
            updates["display_name"] = value
        if "slot" in data:
            value = str(data["slot"]).strip()
            if not value or len(value) > 100:
                return error("invalid_request", "slot must be 1-100 characters.", 400)
            updates["slot"] = value
        if "role" in data:
            value = str(data["role"]).strip().lower()
            if value not in {"admin", "player"}:
                return error("invalid_request", "role must be admin or player.", 400)
            updates["role"] = value
        if "active" in data:
            if not isinstance(data["active"], bool):
                return error("invalid_request", "active must be a boolean.", 400)
            updates["active"] = int(data["active"])
        with transaction(immediate=True) as db:
            current = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not current:
                return error("user_not_found", "User not found.", 404)
            new_role = updates.get("role", current["role"])
            new_active = updates.get("active", current["active"])
            if current["role"] == "admin" and current["active"] == 1 and (
                new_role != "admin" or new_active != 1
            ):
                others = db.execute(
                    "SELECT COUNT(*) FROM users WHERE id<>? AND role='admin' AND active=1",
                    (user_id,),
                ).fetchone()[0]
                if others == 0:
                    return error(
                        "last_admin",
                        "The last active administrator cannot be disabled or demoted.",
                        409,
                    )
            assignments = ",".join(f"{column}=?" for column in updates)
            db.execute(
                f"UPDATE users SET {assignments} WHERE id=?",
                (*updates.values(), user_id),
            )
            audit(
                db,
                "user_updated",
                g.save_sync_user,
                True,
                targetUserId=user_id,
                changed=sorted(data),
            )
        return jsonify(ok=True)

    @routes("/admin/hosts", methods=["GET", "POST"])
    @secured(admin=True)
    def admin_hosts():
        if request.method == "GET":
            with transaction() as db:
                rows = db.execute(
                    "SELECT h.*,u.username,u.display_name,u.role,u.active user_active,"
                    "SUM(CASE WHEN t.revoked_at IS NULL THEN 1 ELSE 0 END) active_token_count,"
                    "MAX(CASE WHEN l.singleton=1 THEN 1 ELSE 0 END) session_active "
                    "FROM authorized_hosts h JOIN users u ON u.id=h.user_id "
                    "LEFT JOIN api_tokens t ON t.host_id=h.id "
                    "LEFT JOIN active_lock l ON l.host_id=h.id "
                    "GROUP BY h.id ORDER BY u.username COLLATE NOCASE,h.name COLLATE NOCASE"
                ).fetchall()
            return jsonify(
                hosts=[
                    {
                        "id": row["id"],
                        "userId": row["user_id"],
                        "username": row["username"],
                        "displayName": display_username(
                            row["username"], row["display_name"]
                        ),
                        "role": row["role"],
                        "clientId": row["client_id"],
                        "name": row["name"],
                        "active": bool(row["active"]),
                        "userActive": bool(row["user_active"]),
                        "activeTokenCount": row["active_token_count"] or 0,
                        "sessionActive": bool(row["session_active"]),
                        # Admin-only endpoint: client IPs never leave admin APIs.
                        "lastIp": row["last_ip"],
                        "createdAt": row["created_at"],
                        "lastSeenAt": row["last_seen_at"],
                        "lastPublishedAt": row["last_published_at"],
                    }
                    for row in rows
                ]
            )

        data = request.get_json(silent=True) or {}
        try:
            user_id = int(data.get("userId", 0))
        except (TypeError, ValueError):
            user_id = 0
        client_id = str(data.get("clientId", "")).strip()
        name = str(data.get("name", "")).strip()
        if user_id < 1 or not client_id or len(client_id) > 200 or not name or len(name) > 100:
            return error(
                "invalid_request", "userId, clientId and computer name are required.", 400
            )
        with transaction(immediate=True) as db:
            user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                return error("user_not_found", "User not found.", 404)
            if user["active"] != 1:
                return error("user_disabled", "Enable the user before adding a computer.", 409)
            try:
                cursor = db.execute(
                    "INSERT INTO authorized_hosts(user_id,client_id,name,active,created_at) VALUES(?,?,?,1,?)",
                    (user_id, client_id, name, iso(utcnow())),
                )
            except sqlite3.IntegrityError:
                return error(
                    "host_exists", "That ClientId is already assigned to a computer.", 409
                )
            audit(
                db,
                "host_created",
                g.save_sync_user,
                True,
                client_id,
                hostId=cursor.lastrowid,
                targetUserId=user_id,
                name=name,
            )
        return jsonify(
            id=cursor.lastrowid,
            userId=user_id,
            clientId=client_id,
            name=name,
            active=True,
        ), 201

    @routes("/admin/hosts/<int:host_id>", methods=["PATCH"])
    @secured(admin=True)
    def update_host(host_id):
        data = request.get_json(silent=True) or {}
        allowed = {"name", "active"}
        if not data or any(key not in allowed for key in data):
            return error("invalid_request", "No supported host fields were supplied.", 400)
        updates = {}
        if "name" in data:
            value = str(data["name"]).strip()
            if not value or len(value) > 100:
                return error("invalid_request", "name must be 1-100 characters.", 400)
            updates["name"] = value
        if "active" in data:
            if not isinstance(data["active"], bool):
                return error("invalid_request", "active must be a boolean.", 400)
            updates["active"] = int(data["active"])
        with transaction(immediate=True) as db:
            host = db.execute(
                "SELECT h.*,u.active user_active FROM authorized_hosts h "
                "JOIN users u ON u.id=h.user_id WHERE h.id=?",
                (host_id,),
            ).fetchone()
            if not host:
                return error("host_not_found", "Computer not found.", 404)
            if updates.get("active") == 1 and host["user_active"] != 1:
                return error("user_disabled", "Enable the user before this computer.", 409)
            assignments = ",".join(f"{column}=?" for column in updates)
            db.execute(
                f"UPDATE authorized_hosts SET {assignments} WHERE id=?",
                (*updates.values(), host_id),
            )
            audit(
                db,
                "host_updated",
                g.save_sync_user,
                True,
                host["client_id"],
                hostId=host_id,
                changed=sorted(data),
            )
        return jsonify(ok=True)


def register_managed_presence_routes(*, routes, transaction, active_lock):
    @routes("/presence", methods=["GET"])
    def presence():
        # ponytail: public lobby readout (state/host/since only). Client IPs
        # stay admin-only via /admin/hosts and admin /status; never here.
        # owner_label is always the admin-set display name, never a username,
        # email or internal id.
        # Read-only by design: anonymous polling must never compete for the
        # single SQLite writer with heartbeats, lock acquisition or uploads.
        with transaction() as db:
            lock = active_lock(db, clear_expired=False)
        if not lock:
            response = jsonify(locked=False)
        else:
            response = jsonify(
                locked=True,
                owner=lock["owner_label"],
                since=lock["created_at"],
            )
        response.headers["Cache-Control"] = "no-store"
        return response
