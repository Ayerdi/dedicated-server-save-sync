# Cambios

## Sin publicar

- Endurece la publicación pública sin cambiar runtime, esquema, API ni protocolo
  del cliente.
- La instalación de producción fija explícitamente backend y cliente a la misma
  release estable (`v2.2.0`) en vez de desplegar la punta móvil de `main`.
- Pages ya no puede desplegarse mientras el repositorio sea privado, ni siquiera
  mediante `workflow_dispatch` manual.
- Wiki y configuración post-publicación exigen checkout limpio, `main`,
  `HEAD == origin/main` y CI verde para el SHA exacto.
- Retira de `main` el workflow de una sola ejecución que publicó `v2.2.0` con
  `contents: write`; futuras releases usan un script explícito con doble build
  reproducible y preflight de CI.
- Amplía el checker documental a enlaces Wiki y Pages, y endurece CI con
  credenciales Git no persistentes, timeouts y ejecución única por PR/main.
- Restaura el detalle histórico de las releases anteriores y documenta la
  diferencia entre la release de producto `v2.2.0` y `clientVersion=1.2.0` del
  adaptador Palworld.

## 2.2.0

- Añade `GET /backup-status` y una tarjeta de estado operativo en el panel.
- Separa el resultado histórico de la versión actual de la configuración
  `enabled` del backup automático.
- Los marcadores `pending_backups` vencidos dejan de mostrarse como pendientes
  eternos y pasan a estado conservador `unknown`.
- `lastCompleted` deja de depender de una ventana fija de 500 eventos.
- Un fallo de `/backup-status` no impide cargar el resto del panel.
- Documenta que `latestVersionBackedUp=true` representa el éxito auditado del
  hook, no una comprobación en vivo del repositorio restic.
- Prepara publicación pública: README ES/EN, web GitHub Pages bilingüe, fuente
  versionada para la wiki y empaquetado reproducible del cliente.
- La release `v2.2.0` se generó desde CI construyendo dos veces el ZIP y
  comprobando su SHA-256 antes de publicarlo.
- El repositorio entra en mantenimiento como implementación estable de
  referencia para Palworld. Las evoluciones multi-juego de gran alcance se
  desarrollarán fuera de este repositorio.

## 2.1.1

- Actualiza dependencias: gunicorn 26, pytest 9.1.1 y ruff 0.16 (con hashes),
  y las acciones de CI (checkout v7, setup-python v7).
- `SAVE_SYNC_POST_PUBLISH_COMMAND` captura cualquier fallo (incluidas
  `ValueError` de `shlex.split`, `OSError`/`FileNotFoundError` al lanzar el
  proceso y la imposibilidad de crear el thread supervisor) de modo que una
  publicación confirmada siempre devuelve 201.
- El marcador `pending_backups` se inserta **atómicamente dentro de la
  transacción de publicación/restore**, cerrando la carrera entre la
  publicación de la versión y su protección frente a la retención.
- La tabla `pending_backups` protege de la retención los ZIP con backup en
  curso; la limpieza del bootstrap usa `started_at` en lugar de borrar todo,
  preservando pendientes de workers colegas vivos.
- El endpoint `DELETE /history/<version>` rechaza (409 `backup_in_progress`)
  borrar versiones con backup en curso; sólo se permite tras liberarse el
  marcador.
- El proceso externo se cancela tras `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS`;
  se registra en auditoría `backup_hook_completed`/`backup_hook_failed` con
  `exitCode` y `timedOut`. El grupo de proceso completo (incluidos nietos) se
  termina en caso de timeout.
- La imagen incluye `restic`; el caché se dirige a un volumen escribible y se
  exige excluirlo del backup (`--exclude`). Se valida
  `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS >= 1`.
- La purga de `pending_backups` obsoletos pasa dentro de
  `cleanup_canonical_versions`, de modo que un worker caído no deja versiones
  protegidas para siempre; el supervisor de backup usa `try/finally` para
  liberar el marcador, auditar y reaplicar la retención incluso en fallos.
- `SCHEMA_VERSION` pasa a 3 al introducir la tabla `pending_backups`.
- La documentación aclara que el backup externo protege al ZIP publicado
  inmutable, pero un `restic backup` sobre el volumen no es un snapshot
  transaccional de SQLite.

## 2.1.0

- Añade `SAVE_SYNC_RETENTION_PER_SLOT` para conservar N versiones por slot.
- Añade `SAVE_SYNC_POST_PUBLISH_COMMAND` para lanzar un backup externo tras
  cada publicación confirmada.

## 2.0.0

- Adopta Apache License 2.0 para código y documentación.
- Actualiza Flask a 3.1.3 por la corrección de seguridad de la rama 3.1.
- Bloquea dependencias transitivas con hashes y añade `pip-audit` y cobertura.
- Añade E2E Docker aislado, modo API-only y `certResolver` parametrizable.
- Registra `PRAGMA user_version=2` y rechaza downgrades implícitos.
- Añade preparación comunitaria, release reproducible y checklist público.
- Convierte el backend en motor de una instancia por `gameKey`.
- Añade rutas canónicas `/api/games/{gameKey}` y cabeceras `X-Save-Sync-*`.
- Generaliza `world_guid` como `save_identity` configurable por adaptador.
- Mantiene alias HTTP y campos Palworld para compatibilidad.
- Separa `SyncGame.ps1` de `client/adapters/palworld`.
- Aísla contenedor, almacenamiento, base y configuración Traefik por juego.
- Añade pruebas con un segundo contrato ficticio basado en `campaignId`.

## 1.2.0

- Unifica los clientes Windows en una única base configurable.
- Incorpora la selección preferente del GUID remoto de la corrección 1.1.
- Añade versión de cliente al manifest ZIP.
- Añade modo `LibraryOnly` y pruebas Pester aisladas.
- Parametriza dominio, red, ForwardAuth, almacenamiento e identidades.
- Sustituye datos del despliegue original por ejemplos neutros.
- Añade documentación para despliegue, operación y otros juegos.

## 1.1.0

- Corrige la ambigüedad cuando el equipo contiene varios mundos locales y la
  autoridad remota ya identifica cuál debe usarse.

## 1.0.0

- Primera implementación operativa de backend, lock, versiones, `worldGuid`,
  cliente PowerShell y publicación atómica.
