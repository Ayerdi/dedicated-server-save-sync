# Cambios

## Sin publicar

- El repositorio entra en mantenimiento como implementación estable de referencia
  para Palworld. Las evoluciones multi-juego de gran alcance se desarrollarán
  fuera de este repositorio.

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
  versionada para la wiki y automatización reproducible del paquete v2.2.0.
- La release v2.2.0 se genera desde CI con ZIP determinista y checksum SHA-256.

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
  `exitCode` y `timedOut`. El grupo de proceso completo se termina en timeout.
- La imagen incluye `restic`; el caché se dirige a un volumen escribible y se
  exige excluirlo del backup (`--exclude`).
- `SCHEMA_VERSION` pasa a 3 al introducir la tabla `pending_backups`.

## 2.1.0

- Añade `SAVE_SYNC_RETENTION_PER_SLOT` para conservar N versiones por slot.
- Añade `SAVE_SYNC_POST_PUBLISH_COMMAND` para lanzar un backup externo tras
  cada publicación confirmada.

## 2.0.0

- Adopta Apache License 2.0 para código y documentación.
- Actualiza Flask a 3.1.3.
- Bloquea dependencias transitivas con hashes y añade `pip-audit` y cobertura.
- Añade E2E Docker aislado, modo API-only y `certResolver` parametrizable.
- Registra `PRAGMA user_version=2` y rechaza downgrades implícitos.
- Convierte el backend en motor de una instancia por `gameKey`.
- Añade rutas canónicas `/api/games/{gameKey}` y cabeceras `X-Save-Sync-*`.
- Generaliza `world_guid` como `save_identity` configurable por adaptador.
- Mantiene alias HTTP y campos Palworld para compatibilidad.
- Separa `SyncGame.ps1` de `client/adapters/palworld`.

## 1.2.0

- Unifica los clientes Windows en una única base configurable.
- Incorpora la selección preferente del GUID remoto.
- Añade versión de cliente al manifest ZIP.
- Añade modo `LibraryOnly` y pruebas Pester aisladas.
- Parametriza dominio, red, ForwardAuth, almacenamiento e identidades.

## 1.1.0

- Corrige la ambigüedad cuando el equipo contiene varios mundos locales y la
  autoridad remota ya identifica cuál debe usarse.

## 1.0.0

- Primera implementación operativa de backend, lock, versiones, `worldGuid`,
  cliente PowerShell y publicación atómica.
