import json

from flask import g, jsonify, request


def register_admin_routes(
    *,
    routes,
    secured,
    transaction,
    audit,
    error,
    active_lock,
    managed_hosts,
    digest,
    iso,
    utcnow,
    token_factory,
):
    @routes("/admin/force-unlock", methods=["POST"])
    @secured(admin=True)
    def force_unlock():
        data = request.get_json(silent=True) or {}
        reason = str(data.get("reason", "")).strip()
        if len(reason) < 5 or len(reason) > 500:
            return error(
                "invalid_request", "reason is required (5-500 characters).", 400
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
                if managed_hosts:
                    rows = db.execute(
                        "SELECT t.id,t.name,t.created_at,t.last_used_at,t.revoked_at,t.host_id,"
                        "u.username,h.client_id,h.name host_name FROM api_tokens t "
                        "JOIN users u ON u.id=t.user_id LEFT JOIN authorized_hosts h ON h.id=t.host_id "
                        "ORDER BY t.id"
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT t.id,t.name,t.created_at,t.last_used_at,t.revoked_at,u.username "
                        "FROM api_tokens t JOIN users u ON u.id=t.user_id ORDER BY t.id"
                    ).fetchall()
            return jsonify(tokens=[dict(r) for r in rows])

        data = request.get_json(silent=True) or {}
        username = str(data.get("username", ""))
        name = str(data.get("name", "")).strip()
        host_id = data.get("hostId")
        if managed_hosts and host_id is None:
            return error(
                "invalid_request",
                "hostId is required for games with managed computers.",
                400,
            )
        if host_id is not None and not managed_hosts:
            return error("invalid_request", "hostId is not supported for this game.", 400)
        if host_id is not None:
            try:
                host_id = int(host_id)
            except (TypeError, ValueError):
                return error("invalid_request", "hostId must be an integer.", 400)
        if not username or not name or (managed_hosts and len(name) > 100):
            return error("invalid_request", "username and name are required.", 400)

        token = token_factory()
        with transaction(immediate=True) as db:
            user = db.execute(
                "SELECT * FROM users WHERE username=? AND active=1", (username,)
            ).fetchone()
            if not user:
                return error("user_not_found", "User not found.", 404)
            if host_id is not None:
                host = db.execute(
                    "SELECT * FROM authorized_hosts WHERE id=? AND user_id=?",
                    (host_id, user["id"]),
                ).fetchone()
                if not host:
                    return error(
                        "host_not_found", "Computer not found for that user.", 404
                    )
                if host["active"] != 1:
                    return error(
                        "host_disabled", "Enable the computer before creating a token.", 409
                    )
            cursor = db.execute(
                "INSERT INTO api_tokens(user_id,name,token_hash,created_at,host_id) VALUES(?,?,?,?,?)",
                (user["id"], name, digest(token), iso(utcnow()), host_id),
            )
            audit(
                db,
                "token_created",
                g.save_sync_user,
                True,
                tokenId=cursor.lastrowid,
                username=username,
                hostId=host_id,
            )
        response = {
            "id": cursor.lastrowid,
            "token": token,
            "username": username,
            "name": name,
        }
        if managed_hosts:
            response["hostId"] = host_id
        return jsonify(response), 201

    @routes("/admin/tokens/<int:token_id>", methods=["DELETE"])
    @secured(admin=True)
    def revoke_token(token_id):
        with transaction(immediate=True) as db:
            changed = db.execute(
                "UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (iso(utcnow()), token_id),
            ).rowcount
            if not changed:
                return error("token_not_found", "Active token not found.", 404)
            audit(db, "token_revoked", g.save_sync_user, True, tokenId=token_id)
        return jsonify(ok=True)

    @routes("/admin/audit", methods=["GET"])
    @secured(admin=True)
    def audit_log():
        limit = min(max(request.args.get("limit", 100, type=int), 1), 500)
        with transaction() as db:
            rows = db.execute(
                "SELECT a.id,a.event,a.at,a.success,a.client_id,a.details,u.username "
                "FROM audit a LEFT JOIN users u ON u.id=a.user_id "
                "ORDER BY a.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return jsonify(
            events=[
                {
                    **dict(row),
                    "success": bool(row["success"]),
                    "details": json.loads(row["details"]),
                }
                for row in rows
            ]
        )
