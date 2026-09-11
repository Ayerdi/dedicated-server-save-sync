# Backups y recuperación

La retención operativa y el backup externo son mecanismos distintos:

- `SAVE_SYNC_RETENTION_PER_SLOT` controla cuántas versiones canónicas se conservan por slot de retención (no necesariamente por equipo físico);
- `SAVE_SYNC_POST_PUBLISH_COMMAND` define el comando de backup externo;
- `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS` limita cada intento.

Publicar una versión y encolarla para backup forman una única transacción SQLite. Un `backup-supervisor` independiente ejecuta el comando, por lo que reiniciar el proceso web no pierde el trabajo pendiente.

El panel y `GET /backup-status` separan la configuración actual del resultado histórico.

`latestVersionBackedUp=true` significa que el supervisor auditó un hook correcto para esa versión. **No** consulta restic en vivo ni demuestra que el snapshot remoto siga existiendo en ese instante.

Las versiones con backup pendiente quedan protegidas frente a retención hasta conocer un resultado final.

Para recuperación y rollback completos consulta [OPERATIONS.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/docs/OPERATIONS.md).

[[Backups-and-Recovery|Read in English]]
