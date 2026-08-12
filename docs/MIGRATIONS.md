# Schema migrations

SQLite stores the schema level in `PRAGMA user_version`. The current application supports schema **3** and applies idempotent DDL under `flock` and `BEGIN IMMEDIATE` during startup.

## Rules

- A compatible schema `0` database is normalized to `3` after required columns and triggers are validated.
- Schema `3` introduced `pending_backups`, which is the durable queue consumed by the external backup supervisor.
- Repeated startup keeps `user_version=3`.
- A database with a newer version is rejected. The application never attempts an implicit downgrade.
- A legacy Palworld Sync v1 database with the old `world_guid` layout is rejected and must remain on a separate volume.
- Future migrations must be incremental, transactional and tested from every supported source version.

## Before upgrading

1. Prevent new sessions and confirm no active lock exists.
2. Check `/backup-status` and do not silently discard uncertain pending backup work.
3. Create a consistent database backup with the SQLite Backup API rather than copying a live WAL database file.
4. Back up every ZIP referenced by `versions`, including versions protected by `pending_backups`.
5. Test restoring the backup to another path.
6. Deploy and verify `PRAGMA integrity_check` and `PRAGMA user_version`.

See [OPERATIONS.md](OPERATIONS.md) for backup commands and operational details.

## Rollback

Rolling back an image is safe only when the older version understands the current schema. Otherwise stop both the web backend and backup supervisor, then restore a matching SQLite snapshot and its referenced ZIP files together. Never reuse `-wal` or `-shm` sidecars from another run.
