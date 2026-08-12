# Backups y recuperación

La retención operativa y el backup externo son mecanismos distintos.

- `SAVE_SYNC_RETENTION_PER_SLOT`: versiones canónicas por slot.
- `SAVE_SYNC_POST_PUBLISH_COMMAND`: comando externo tras publicar.
- `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS`: timeout del hook.

El panel muestra si el backup automático está habilitado y el último resultado
auditado.

`latestVersionBackedUp=true` **no** comprueba restic en vivo: indica que el hook
de esa versión terminó correctamente.

Para recuperación completa y rollback consulta
[OPERATIONS.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/docs/OPERATIONS.md).
