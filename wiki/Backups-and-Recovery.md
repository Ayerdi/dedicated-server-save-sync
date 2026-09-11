# Backups and recovery

Operational retention and external backup are separate mechanisms:

- `SAVE_SYNC_RETENTION_PER_SLOT` controls how many canonical versions are retained per retention slot;
- `SAVE_SYNC_POST_PUBLISH_COMMAND` defines the external backup command;
- `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS` limits one backup attempt.

Publication and backup queue insertion happen in one SQLite transaction. A separate `backup-supervisor` executes the command, so a web-worker restart does not lose pending backup work.

The panel and `GET /backup-status` distinguish current backup configuration from historical results.

`latestVersionBackedUp=true` means the supervisor recorded a successful hook result for that version. It **does not** query restic live or prove that the remote snapshot still exists at this exact moment.

Pending backup versions stay protected from retention until a final result is known.

For full disaster-recovery and rollback procedures see [OPERATIONS.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/docs/OPERATIONS.md).

[[Backups-y-recuperacion|Leer en español]]
