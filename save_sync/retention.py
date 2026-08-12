from pathlib import Path


def cleanup_canonical_versions_locked(
    db,
    storage,
    retention_per_slot,
    identity_for_username,
    logger,
):
    """Conserva las últimas N versiones por slot.

    El llamador debe mantener una transacción de escritura SQLite. Las versiones
    con una fila en ``pending_backups`` permanecen protegidas hasta que el
    supervisor durable resuelva el backup. El filesystem se reconcilia dentro
    del mismo lock para que publicación/restore no puedan intercalarse entre el
    snapshot de metadata y los unlink.
    """
    storage = Path(storage)
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
            db.execute("DELETE FROM versions WHERE version=?", (row["version"],))
        else:
            kept_per_slot[slot] = kept + 1

    referenced = {
        storage / row["path"] for row in db.execute("SELECT path FROM versions")
    }
    candidates = set((storage / "backups").glob("save-v*.zip"))
    for path in candidates - referenced:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # La metadata obsoleta ya quedó reconciliada. El ZIP huérfano se
            # reintentará en el siguiente cleanup/arranque.
            logger.exception("No se pudo eliminar ZIP obsoleto %s", path)
