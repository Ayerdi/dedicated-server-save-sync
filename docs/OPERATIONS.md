# Despliegue y operación

> **Ámbito estable:** el repositorio se mantiene como referencia de Palworld.
> Las variables genéricas y el aislamiento por `gameKey` forman parte de la
> arquitectura existente; las notas sobre otros juegos son referencia técnica y
> no una promesa de soporte ni un roadmap activo.

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
| `SAVE_SYNC_CONTAINER_NAME` | Nombre único del backend; el deploy lo deriva del juego |
| `SAVE_SYNC_BACKUP_CONTAINER_NAME` | Nombre único del supervisor; el deploy lo deriva del juego |
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
| `SAVE_SYNC_POST_PUBLISH_COMMAND` | Comando de backup consumido por el supervisor durable |
| `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS` | Timeout de cada intento (por defecto 1800) |
| `SAVE_SYNC_BACKUP_POLL_SECONDS` | Sondeo de la cola SQLite (por defecto 1) |
| `SAVE_SYNC_PROXY_SECRET` | Cabecera interna proxy/backend |
| `SAVE_SYNC_CSRF_SECRET` | Firma CSRF del panel |

Los dos últimos valores deben ser independientes, aleatorios y tener al menos
32 caracteres. No deben aparecer en Traefik estático, logs o Git.

## Retención y backup externo durable

Cada usuario se asocia a un `slot` mediante
`SAVE_SYNC_USER_IDENTITIES_JSON`. `SAVE_SYNC_RETENTION_PER_SLOT` controla
cuántas versiones recientes se conservan por slot (por defecto 1). Con dos
slots y retención 1, el máximo normal son dos ZIP; con retención 5, hasta
diez. Mientras exista un backup pendiente pueden conservarse temporalmente más
versiones: **la seguridad del backup tiene prioridad sobre el límite de
retención**.

La ejecución del backup no pertenece a Gunicorn. Upload y restore hacen una
única transacción SQLite que publica la versión y, si
`SAVE_SYNC_POST_PUBLISH_COMMAND` está configurado, inserta su fila en
`pending_backups`. Esa tabla es una **cola durable**, no un marker efímero. La
respuesta HTTP puede terminar y cualquier worker web puede morir sin perder el
trabajo pendiente.

El servicio Compose `backup-supervisor` comparte el mismo volumen privado y es
el único proceso que consume esa cola en producción. Para cada intento:

1. reclama la versión pendiente y refresca `started_at`;
2. audita `backup_hook_started`;
3. ejecuta `SAVE_SYNC_POST_PUBLISH_COMMAND` en un process-group aislado con:
   `SAVE_SYNC_PUBLISHED_VERSION`, `SAVE_SYNC_PUBLISHED_PATH`,
   `SAVE_SYNC_PUBLISHED_IDENTITY` y
   `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS`;
4. aplica el timeout configurado y termina el grupo con SIGTERM/SIGKILL si hace
   falta;
5. en una única transacción, elimina la fila, audita
   `backup_hook_completed`/`backup_hook_failed` y reaplica retención.

La finalización es **at-least-once**. Si el supervisor o el contenedor mueren
antes de confirmar esa transacción, la fila SQLite permanece y se vuelve a
intentar tras el reinicio. Si una parada controlada llega durante un backup, el
supervisor termina el hijo y conserva igualmente la fila. Por ello el comando
de backup debe ser idempotente o tolerar repetición, como `restic backup`.

Un exit code distinto de cero o un timeout ya observado sí se registra como
fallo final de ese intento y libera la fila: no se reintenta indefinidamente un
comando que terminó de forma conocida. Un crash antes de poder registrar el
resultado sí provoca retry porque el sistema no puede saber si el destino
externo llegó a recibir el snapshot.

Los pending **no se purgan por edad**. `stalePending` en `/backup-status` es una
señal de observabilidad que indica que la fila lleva más de `timeout + 60s`, no
un permiso para que retención borre el ZIP. Esta decisión evita pérdida
silenciosa si el supervisor permanece caído durante horas o días.

### Restic reproducible

La imagen incluye **Restic 0.18.0** desde los assets oficiales, fijado por
versión y SHA-256 para `amd64` y `arm64`. El build falla si el asset no coincide
y CI vuelve a comprobar `restic version` dentro de la imagen. No se usa
`apt install restic`, por lo que reconstruir la misma revisión no acepta de
forma silenciosa otra versión del binario.

Configura `RESTIC_REPOSITORY` y `RESTIC_PASSWORD` (o el mecanismo equivalente)
como secretos del despliegue. El cache se dirige a
`RESTIC_CACHE_DIR=/data/save-sync/temporary`. Excluye ese directorio del backup:

```dotenv
SAVE_SYNC_POST_PUBLISH_COMMAND=restic backup /data/save-sync --exclude /data/save-sync/temporary
```

### Operar el supervisor

Estado y logs:

```bash
docker compose ps backup-supervisor
docker compose logs --tail=100 backup-supervisor
```

Su healthcheck exige una heartbeat reciente y acceso válido al esquema SQLite.
`config/deploy.sh` no publica la ruta Traefik hasta que **backend y supervisor**
están healthy.

Si se desea desactivar voluntariamente el backup, comprueba antes
`/backup-status`. Una fila pendiente se conserva aunque posteriormente se vacíe
el comando: resuelve el backup o decide administrativamente qué hacer con esa
versión antes de retirar definitivamente el supervisor. No borres
`pending_backups` a mano como procedimiento normal.

> **Coherencia del backup:** el supervisor protege el ZIP publicado de la
> retención mientras el backup lo necesita, pero `restic backup
> /data/save-sync` no crea por sí solo un snapshot transaccional de SQLite. Con
> `journal_mode=WAL` y uploads concurrentes, para un DR completo de la base
> combine restic con la [SQLite Backup API](https://www.sqlite.org/backupapi.html)
> o suspenda el servicio durante el backup del volumen. El caso fuerte
> garantizado por Save Sync es la integridad del **ZIP publicado** individual,
> que es inmutable tras el commit.

## Despliegue

```bash
config/deploy.sh
```

El script valida `.env`, renderiza la ruta Traefik privada, ejecuta
`docker compose config`, construye, prepara el almacenamiento y levanta el
backend junto al supervisor durable. Antes de publicar la ruta mediante rename
verifica:

- backend healthy;
- `backup-supervisor` healthy;
- ausencia de puertos host públicos no previstos;
- API anónima `401`;
- panel anónimo redirigido al login.

En modo `disabled` verifica API y stack, y omite deliberadamente la ruta del
panel. La administración sigue disponible por endpoints Bearer con un token de
rol `admin`.

El script valida que `SAVE_SYNC_GAME_KEY` coincida con
`config/games/<gameKey>.json`. Los nombres de proyecto, backend, supervisor,
alias de red y ruta Traefik incorporan el juego para no colisionar.

### Referencia: aislamiento de otra instancia de juego

Esta sección documenta la capacidad arquitectónica heredada; **no convierte
`example-game` ni otros títulos en integraciones soportadas**. Para
experimentación técnica, otro checkout/directorio debe usar `.env`, volumen y
proyecto Compose independientes, por ejemplo:

```dotenv
SAVE_SYNC_GAME_KEY=example-game
SAVE_SYNC_HOST_STORAGE_PATH=/srv/save-sync/example-game
SAVE_SYNC_COMPOSE_PROJECT=save-sync-example-game
```

También requeriría `config/games/example-game.json` y un adaptador probado. No
compartir base de datos ni directorio de almacenamiento entre juegos. Consulta
[ADAPTING-OTHER-GAMES.md](ADAPTING-OTHER-GAMES.md) como referencia de diseño.

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

Restaura la ruta Traefik anterior si existe y detiene backend y supervisor sin
borrar datos. Este script no revierte automáticamente cambios de esquema.

Para volver a una imagen incompatible con el esquema:

1. crear un backup coherente del estado actual;
2. retirar la ruta;
3. detener el stack;
4. mover fuera de la ruta live la base y sus sidecars `-wal`/`-shm`;
5. restaurar el snapshot mediante SQLite Backup API hacia un temporal del mismo
   filesystem, hacer `fsync` y publicar con `os.replace`;
6. no copiar sidecars del snapshot ni reutilizar WAL antiguos;
7. arrancar la imagen anterior y verificar antes de reabrir la ruta.

## Incidentes frecuentes

### Supervisor de backup degradado

Si `/backup-status` muestra `pending` o `stalePending` durante más tiempo del
esperado, revisa primero:

```bash
docker compose ps backup-supervisor
docker compose logs --tail=200 backup-supervisor
```

No elimines la versión pendiente ni su ZIP. Tras corregir el contenedor, las
filas que no tengan un resultado final conocido se reclamarán automáticamente.
Si el hook devuelve un fallo explícito, aparecerá `backup_hook_failed` y el
marker se liberará porque el resultado ya es conocido.

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