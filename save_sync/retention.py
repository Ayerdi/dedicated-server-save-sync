from pathlib import Path


def prune_canonical_versions_locked(
    db,
    retention_per_slot,
    identity_for_username,
):
    """Aplica la retención únicamente a metadata SQLite.

    El llamador debe mantener una transacción de escritura. Las versiones con
    una fila en ``pending_backups`` permanecen protegidas hasta que el
    supervisor durable resuelva el backup. No se toca el filesystem aquí: así
    un crash antes del COMMIT nunca puede dejar metadata restaurada por rollback
    apuntando a un ZIP que ya fue eliminado.
    """
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


def reconcile_unreferenced_files_locked(db, storage, logger):
    """Elimina ZIPs no referenciados después de confirmar la metadata.

    Debe ejecutarse bajo un nuevo ``BEGIN IMMEDIATE``. La segunda adquisición
    revalida referencias antes de cada borrado y evita que una publicación
    concurrente reutilice un nombre de ZIP huérfano entre el COMMIT de retención
    y el unlink. Un crash aquí solo puede dejar un fichero huérfano, nunca una
    fila SQLite que apunte a un fichero borrado por una transacción revertida.
    """
    storage = Path(storage)
    referenced = {
        storage / row["path"] for row in db.execute("SELECT path FROM versions")
    }
    candidates = set((storage / "backups").glob("save-v*.zip"))
    for path in candidates - referenced:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # La metadata obsoleta ya quedó confirmada. El ZIP huérfano se
            # reintentará en el siguiente cleanup/arranque.
            logger.exception("No se pudo eliminar ZIP obsoleto %s", path)
