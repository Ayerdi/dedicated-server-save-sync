# Backups and Recovery

Operational retention and external backup are separate mechanisms.

- `SAVE_SYNC_RETENTION_PER_SLOT`: canonical versions per slot.
- `SAVE_SYNC_POST_PUBLISH_COMMAND`: external command after publication.
- `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS`: hook timeout.

The panel shows whether automatic backup is currently enabled and the latest
audited result.

`latestVersionBackedUp=true` does **not** query restic live. It means the hook
for that version completed successfully.

See
[OPERATIONS.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/docs/OPERATIONS.md)
for full recovery and rollback.
