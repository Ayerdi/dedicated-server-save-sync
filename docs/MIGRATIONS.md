# Schema migrations

SQLite stores the schema level in `PRAGMA user_version`. The current application supports schema **4** and applies idempotent DDL under `flock` and `BEGIN IMMEDIATE` during startup.

## Rules

- A compatible schema `0` database is normalized to `4` after required columns and triggers are validated.
- Schema `3` introduced `pending_backups`, which is the durable queue consumed by the external backup supervisor.
- Schema `4` adds persisted display/retention identity plus the generic storage needed by opt-in managed-computer deployments: registered hosts, optional computer-bound API tokens and computer provenance for locks/publications. The experimental Valheim configuration opts in; Palworld does not.
- Existing schema `3` users and tokens remain valid after migration. Legacy unbound tokens are intentionally preserved until an administrator rotates them to computer-bound tokens.
- If a schema-3 database is upgraded into a game with `managedHosts: true`, any pre-existing active lock has no trusted computer provenance and is therefore fail-closed: it cannot heartbeat or publish. The lock is preserved until normal expiry or explicit administrative force-unlock so a second host is never released early.
- Repeated startup keeps `user_version=4`.
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
