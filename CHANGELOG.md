# Cambios

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
