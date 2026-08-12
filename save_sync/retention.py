from pathlib import Path


def prune_canonical_versions_locked(
    db,
    retention_per_slot,
    identity_for_username,
):
    """Applies retention to SQLite metadata only.

    The caller must hold a write transaction. Versions with
    a row in ``pending_backups`` remain protected until
    the durable supervisor resolves the backup. The filesystem is not touched here, so
    a crash before COMMIT can never leave rollback-restored metadata
    pointing to a ZIP that has already been deleted.
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
    """Deletes unreferenced ZIPs after metadata is committed.

    Must run under a new ``BEGIN IMMEDIATE``. The second acquisition
    revalidates references before each delete and prevents a concurrent publication
    from reusing an orphan ZIP name between the retention COMMIT
    and unlink. A crash here can leave only an orphan file, never a
    SQLite row pointing to a file deleted by a rolled-back transaction.
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
            # Obsolete metadata has already been committed. The orphan ZIP
            # will be retried during the next cleanup/startup.
            logger.exception("Could not remove obsolete ZIP %s", path)
