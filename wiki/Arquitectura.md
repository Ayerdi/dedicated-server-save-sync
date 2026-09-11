# Arquitectura y modelo de seguridad

`v2.2.2` sigue siendo la release estable de Palworld. El backend actual de `main` está modularizado internamente y también soporta el adaptador experimental de Valheim mediante capacidades por juego.

## Módulos del backend

- `save_sync/app.py` — composición Flask, HTTP/autenticación y wiring;
- `save_sync/database.py` — conexión SQLite, schema y migraciones;
- `save_sync/sessions.py` — lock, heartbeat, unlock y revalidación de equipos;
- `save_sync/publications.py` — validación de upload, publicación atómica y restore;
- `save_sync/game_config.py` — identidad/capacidades por juego;
- `save_sync/managed.py` — gestión opcional de usuarios/equipos;
- `save_sync/admin.py` — tokens, audit y force-unlock;
- `save_sync/panels.py` — variantes del panel web;
- `save_sync/retention.py` — retención/reconciliación;
- `save_sync/backup_supervisor.py` — worker durable de backup externo.

Sigue siendo una sola aplicación, no una división en microservicios. Los módulos hacen explícitos los límites transaccionales.

## Autoridad

La base asigna versiones enteras crecientes. `current_save` apunta a un ZIP publicado e inmutable. Los timestamps de fichero nunca son autoridad de versión.

Cada adaptador entrega un `saveIdentity` canónico:

- Palworld: `worldGuid`;
- Valheim experimental: `worldUid` de 64 bits con signo.

Una publicación debe coincidir simultáneamente con la identidad actual, el `baseVersion` actual y un lock/sesión válidos.

## Publicación atómica

El upload se prepara y valida antes de que una transacción `BEGIN IMMEDIATE` vuelva a comprobar identidad, versión, lock/sesión y autorización actual. El ZIP inmutable, `versions`, `current_save`, la cola de backup y la liberación del lock se confirman como un único cambio de autoridad.

Los errores inesperados hacen rollback. Los rechazos de dominio esperados conservan el mismo comportamiento de auditoría que las rutas anteriores al refactor.

## Restore

El restore histórico usa deliberadamente dos transacciones de escritura: snapshot/revalidación inicial, copia+hash fuera del lock de escritura y revalidación completa justo antes de publicar la copia como una **nueva versión superior**.

## Equipos gestionados

Los juegos con `managedHosts: true` separan usuario de PC físico. El token vinculado debe seguir perteneciendo al usuario activo, al equipo exacto y al mismo `ClientId` cuando se ejecuta la transacción de escritura. Consulta [[Equipos-Gestionados]].

## Seguridad del cliente

El proceso que escribe el save debe detenerse antes de archivarlo. Palworld usa su REST local para guardar/apagar. Valheim experimental usa CTRL+C, espera a que termine el proceso y valida una generación final completa.

Valheim también reserva TTL suficiente para un apagado controlado. Que el TTL haya caducado **no demuestra** que un servidor antiguo bloqueado/fallido se haya detenido.

Para más detalle consulta [docs/ARCHITECTURE.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/docs/ARCHITECTURE.md).

[[Architecture|Read in English]]

