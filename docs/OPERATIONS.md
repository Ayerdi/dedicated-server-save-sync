# Despliegue y operación

## Preparación

1. Crear una red Docker compartida con Traefik si no existe:

   ```bash
   docker network create traefik_proxy
   ```

2. Copiar `.env.example` a `.env` o ejecutar:

   ```bash
   config/deploy.sh --init-env
   ```

3. Revisar dominio, rutas, red, URL ForwardAuth e identidades.
4. Crear la ruta host de almacenamiento; el despliegue ajustará propietario y
   permisos mediante un contenedor efímero limitado.
5. Verificar que Traefik y el outpost Authentik comparten la red configurada.

Si solo se necesita la API Bearer, usa `SAVE_SYNC_PANEL_MODE=disabled`: se
renderiza una ruta sin panel ni ForwardAuth. No se crea un panel anónimo.

No usar almacenamiento NFS/SMB para SQLite. No situar el volumen dentro del
document root del servidor web.

Save Sync v2 no debe apuntarse directamente a una base Palworld Sync v1: aquella
tabla exige `world_guid` en cada inserción y no representa el contrato genérico.
El arranque lo detecta y falla de forma explícita. Mantener el servicio v1
existente o inicializar v2 con otro volumen; cualquier importación futura debe
ser una operación administrativa diseñada y probada, no una copia de SQLite.

## Variables

| Variable | Propósito |
|---|---|
| `SAVE_SYNC_GAME_KEY` | Identificador del adaptador/despliegue |
| `SAVE_SYNC_GAME_CONFIG_PATH` | JSON del juego dentro del contenedor |
| `SAVE_SYNC_CONTAINER_NAME` | Nombre único; el deploy lo deriva del juego |
| `SAVE_SYNC_HOST_STORAGE_PATH` | Directorio privado absoluto del host |
| `SAVE_SYNC_STORAGE_PATH` | Montaje interno, normalmente `/data/save-sync` |
| `SAVE_SYNC_DB_PATH` | SQLite dentro del montaje |
| `SAVE_SYNC_PUBLIC_HOST` | Host de las reglas Traefik |
| `SAVE_SYNC_PUBLIC_BASE_URL` | URL HTTPS utilizada por verificación |
| `SAVE_SYNC_PUBLIC_ROOT` | Árbol público que el almacenamiento no puede ocupar |
| `SAVE_SYNC_TRAEFIK_DYNAMIC_DIR` | Directorio dinámico de Traefik en el host |
| `SAVE_SYNC_PROXY_NETWORK` | Red Docker externa compartida |
| `SAVE_SYNC_AUTHENTIK_FORWARD_AUTH_URL` | Endpoint interno ForwardAuth |
| `SAVE_SYNC_PANEL_MODE` | `authentik` o `disabled` |
| `SAVE_SYNC_TRAEFIK_CERT_RESOLVER` | Resolver TLS existente en Traefik |
| `SAVE_SYNC_WEB_USERS` | Allowlist `usuario:rol` |
| `SAVE_SYNC_USER_IDENTITIES_JSON` | Display names y slots de retención |
| `SAVE_SYNC_MAX_UPLOAD_SIZE` | Tamaño ZIP máximo |
| `SAVE_SYNC_LOCK_TTL_SECONDS` | TTL del lock, 300 por defecto |
| `SAVE_SYNC_HEARTBEAT_INTERVAL_SECONDS` | Intervalo recomendado, 60 |
| `SAVE_SYNC_RETENTION_PER_SLOT` | Versiones por slot (por defecto 1) |
| `SAVE_SYNC_POST_PUBLISH_COMMAND` | Comando externo de backup tras publicar |
| `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS` | Timeout del backup (por defecto 1800) |
| `SAVE_SYNC_PROXY_SECRET` | Cabecera interna proxy/backend |
| `SAVE_SYNC_CSRF_SECRET` | Firma CSRF del panel |

Los dos últimos valores deben ser independientes, aleatorios y tener al menos
32 caracteres. No deben aparecer en Traefik estático, logs o Git.

## Retención y backup externo

Cada usuario se asocia a un `slot` mediante
`SAVE_SYNC_USER_IDENTITIES_JSON`. `SAVE_SYNC_RETENTION_PER_SLOT` controla
cuántas versiones recientes se conservan por slot (por defecto 1). Con dos
slots y retención 1, el máximo normal son dos ZIP; con retención 5, hasta
diez. El límite de espacio sigue siendo deliberado y configurable.

Tras cada publicación confirmada se ejecuta
`SAVE_SYNC_POST_PUBLISH_COMMAND` con las variables de entorno
`SAVE_SYNC_PUBLISHED_VERSION`, `SAVE_SYNC_PUBLISHED_PATH`,
`SAVE_SYNC_PUBLISHED_IDENTITY` y `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS`.
El comando se lanza en segundo plano, sin bloquear la respuesta al cliente, y
cualquier fallo (incluido no poder arrancar el proceso) no invalida la versión
publicada. Se respeta su timeout (`SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS`,
1800s por defecto) y se graba en auditoría `backup_hook_completed` o
`backup_hook_failed` con el `exitCode` real.

> **Límite de resiliencia del worker:** el proceso de backup se lanza en segundo
> plano con `start_new_session=True` y se supervisa desde un thread *daemon* del
> worker que lo armó. Si ese worker muere (p. ej. reinicio de Gunicorn), el
> thread desaparece y el proceso externo queda huérfano: se pierde su timeout.
> Tras `started_at < ahora - (timeout + 60s)`, otro `cleanup_canonical_versions`
> purga el marcador stale y reabre la retención, pero el proceso externo podría
> seguir ejecutable mientras tanto. Para la carga prevista (un par de hosts) se
> asume; un scheduler/queue dedicado cambiaría esta ecuación.

La imagen incluye `restic`; configúrese `RESTIC_REPOSITORY` y
`RESTIC_PASSWORD` (o su equivalente) como secretos del despliegue. El cache de
restic se dirige a `RESTIC_CACHE_DIR=/data/save-sync/temporary`, dentro del
volumen escribible. Excluya ese directorio del backup (ejemplo recomendado):

```dotenv
SAVE_SYNC_POST_PUBLISH_COMMAND=restic backup /data/save-sync --exclude /data/save-sync/temporary
```

> **Coherencia del backup:** el hook protege el ZIP publicado actual de la
> retención mientras el backup lo necesita, pero no crea un snapshot
> atómico de SQLite. Con `journal_mode=WAL` y uploads concurrentes,
> `restic backup /data/save-sync` no es transaccional sobre la base. Para un
> DR completo y coherente, combine `restic` (o su herramienta) con la
> [SQLite Backup API](https://www.sqlite.org/backupapi.html) o suspenda el
> servicio durante el backup del volumen. El único caso fuerte garantizado por
> Save Sync es la integridad del **ZIP publicado** individual, que es
> inmutable tras el commit.

## Despliegue

```bash
config/deploy.sh
```

El script valida `.env`, renderiza la ruta Traefik privada, ejecuta
`docker compose config`, construye, levanta solo este servicio, verifica health,
publica la ruta mediante rename y comprueba:

- contenedor healthy;
- ausencia de puertos host publicados;
- API anónima `401`;
- panel anónimo redirigido al login.

En modo `disabled` verifica API y contenedor, y omite deliberadamente la ruta
del panel. La administración sigue disponible por endpoints Bearer con un token
de rol `admin`.

El script valida que `SAVE_SYNC_GAME_KEY` coincida con
`config/games/<gameKey>.json`. Los nombres de proyecto, contenedor, alias de red
y ruta Traefik incorporan el juego para no colisionar.

### Un juego adicional

Usar otro checkout o directorio de despliegue con su propio `.env`. Cambiar al
menos:

```dotenv
SAVE_SYNC_GAME_KEY=example-game
SAVE_SYNC_HOST_STORAGE_PATH=/srv/save-sync/example-game
SAVE_SYNC_COMPOSE_PROJECT=save-sync-example-game
```

Añadir `config/games/example-game.json` y el adaptador Windows correspondiente.
No compartir base de datos ni directorio de almacenamiento entre juegos.

Para una validación sin infraestructura externa consulta
[LOCAL-DEVELOPMENT.md](LOCAL-DEVELOPMENT.md). Ese modo enlaza solo localhost y
no debe exponerse a Internet.

## Primer token

La opción preferida es acceder al panel como administrador y crear un token por
equipo. El valor plano se muestra una sola vez.

Como bootstrap controlado puede definirse temporalmente
`SAVE_SYNC_BOOTSTRAP_TOKENS_JSON`. Debe retirarse del entorno después del primer
arranque. SQLite solo guarda SHA-256, pero el `.env` sí contendría el valor plano
mientras la variable exista.

## Backup coherente de SQLite

No copiar directamente una base WAL en ejecución. Usar la SQLite Backup API:

```bash
python3 - /ruta/save-sync.sqlite3 /ruta/backup.sqlite3 <<'PY'
import sqlite3
import sys

source, target = sys.argv[1:]
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
print(sqlite3.connect(target).execute("PRAGMA integrity_check").fetchone()[0])
PY
```

Guardar el backup fuera del volumen servido y con modo `0600`.

## Rollback de despliegue

```bash
config/rollback.sh
```

Restaura la ruta Traefik anterior si existe y detiene el contenedor sin borrar
datos. Este script no revierte automáticamente cambios de esquema.

Para volver a una imagen incompatible con el esquema:

1. crear un backup coherente del estado actual;
2. retirar la ruta;
3. detener el servicio;
4. mover fuera de la ruta live la base y sus sidecars `-wal`/`-shm`;
5. restaurar el snapshot mediante SQLite Backup API hacia un temporal del mismo
   filesystem, hacer `fsync` y publicar con `os.replace`;
6. no copiar sidecars del snapshot ni reutilizar WAL antiguos;
7. arrancar la imagen anterior y verificar antes de reabrir la ruta.

## Incidentes frecuentes

### Lock tras caída del PC

Esperar el TTL y consultar `status`. Si sigue bloqueado por un problema de
reloj/estado, un administrador puede usar `force-unlock` dejando motivo en la
auditoría. No forzar mientras el otro servidor pueda seguir ejecutándose.

### Upload sin respuesta

El cliente consulta `status` y reconcilia por versión, SHA-256, identidad y actor. Si
no puede confirmar, conserva el ZIP en `client/data/pending-uploads` y mantiene
`pending-session.json`. No cambiar manualmente `baseVersion`.

### Varios mundos locales

El cliente prefiere el GUID remoto si su carpeta existe. En una inicialización
vacía debe configurarse `InitialWorldGuid` o dejar un único mundo inequívoco. No
borrar mundos locales automáticamente.

### Heartbeat degradado

Tras tres fallos el cliente cierra PalServer y no publica automáticamente. El
save local queda pendiente para revisión. Esta decisión evita continuar jugando
sin exclusión fiable.
