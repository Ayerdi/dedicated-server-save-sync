# Cambios

## 2.1.1

- `SAVE_SYNC_POST_PUBLISH_COMMAND` captura cualquier fallo (incluidas
  `ValueError` de `shlex.split` y `OSError`/`FileNotFoundError` al lanzar el
  proceso) de modo que una publicación confirmada siempre devuelve 201.
- La tabla `pending_backups` protege de la retención los ZIP con backup en
  curso; la limpieza del bootstrap usa `started_at` en lugar de borrar todo,
  preservando pendientes de workers colegas vivos.
- El proceso externo se cancela tras `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS`;
  se registra en auditoría `backup_hook_completed`/`backup_hook_failed` con
  `exitCode` y `timedOut`.
- La imagen incluye `restic` y dirige su caché a un volumen escribible.

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
