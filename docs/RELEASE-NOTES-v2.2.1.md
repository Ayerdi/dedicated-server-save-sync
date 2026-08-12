# Dedicated Server Save Sync v2.2.1

`v2.2.1` es la release de mantenimiento que cierra el hardening operativo antes de la publicación pública del repositorio.

No cambia el protocolo del cliente, el formato ZIP/save ni el esquema SQLite (permanece en v3). El cambio principal está en cómo se supervisan y retienen los backups externos.

## Backup durable independiente de Gunicorn

- `pending_backups` pasa de marker efímero a cola durable en SQLite.
- Publicar/restaurar una versión y encolar su backup forman el mismo commit SQLite.
- Un sidecar `backup-supervisor`, independiente del proceso web, consume la cola y ejecuta el hook externo.
- Si cae Gunicorn, el backup continúa.
- Si cae el propio supervisor, la fila permanece y se reintenta al arrancar con semántica **at-least-once**.
- El comando externo debe permanecer en foreground y ser idempotente o tolerar reintentos.

## Crash-safety y retención

La retención de backend y supervisor usa dos fases:

1. confirma en SQLite el resultado, auditoría, marker y retención de metadata;
2. reabre un write-lock, revalida las referencias actuales y solo entonces elimina ZIPs físicos que siguen huérfanos.

Un crash tras el commit puede dejar un ZIP de más, que una reconciliación posterior elimina. No puede provocar que un rollback de SQLite deje metadata apuntando a un ZIP que ya fue borrado por la misma operación de retención.

Las versiones con backup pendiente permanecen protegidas aunque el marker sea antiguo. `stalePending` queda como señal de observabilidad, no como permiso para borrar la cola.

## Supervisor y healthcheck

- Rechaza bases cuyo `PRAGMA user_version` no coincida exactamente con el esquema soportado.
- El healthcheck exige heartbeat reciente y esquema correcto.
- Si existe cola pendiente pero `SAVE_SYNC_POST_PUBLISH_COMMAND` está vacío, el supervisor se marca unhealthy.
- Los hooks se ejecutan en un process-group propio; timeout/parada escalan `SIGTERM` → `SIGKILL` sobre todo el grupo, incluso si el proceso líder ya terminó.

## Restic reproducible

Restic 0.18.0 deja de instalarse desde APT. La imagen descarga los binarios oficiales para `amd64`/`arm64`, valida SHA-256 fijados y CI comprueba que la imagen resultante expone exactamente `restic 0.18.0`.

## Despliegue y recuperación

- `config/deploy.sh` exige que backend y `backup-supervisor` estén healthy antes de publicar la ruta Traefik.
- Rollback detiene ambos servicios sin borrar datos.
- El stack local/E2E inicializa de forma explícita los permisos del volumen compartido.

## Validación

El candidato que introduce este hardening se validó con:

- Ruff;
- checker de documentación;
- **132 tests** con **88,38 %** de cobertura (mínimo 85 %);
- `pip-audit` sin vulnerabilidades conocidas;
- Docker Compose y Docker build;
- comprobación de Restic 0.18.0 dentro de la imagen;
- E2E normal;
- E2E que mata el contenedor web durante un backup;
- E2E que mata con SIGKILL el supervisor y exige reintento desde SQLite;
- Pester para el cliente Windows;
- Gitleaks sobre el historial Git.

La CI de `main` posterior al merge del hardening también quedó completamente verde.

## Compatibilidad

No hay cambios deliberados en:

- API pública de sincronización;
- protocolo del cliente Windows;
- formato de saves/ZIP;
- `saveIdentity` / `worldGuid`;
- esquema SQLite v3.

El adaptador Palworld sigue identificándose internamente como `clientVersion=1.2.0`; ese número corresponde al componente Windows y es independiente de la release del producto `v2.2.1`.
