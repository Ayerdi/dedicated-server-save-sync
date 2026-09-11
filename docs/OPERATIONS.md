# Deployment and operations

> **Stable scope:** `v2.2.2` is maintained as the Palworld reference release. `main` also contains an experimental Valheim deployment profile and managed-host capability. Treat those development-tree features as pre-release and keep them isolated from stable Palworld data.

## Production preparation

1. Create the shared Docker network used by Traefik if it does not already exist:

   ```bash
   docker network create traefik_proxy
   ```

2. Generate `.env` with:

   ```bash
   config/deploy.sh --init-env
   ```

3. Review domain, paths, Docker network, ForwardAuth URL and user identities.
4. Create a private host storage path. The deployment helper adjusts ownership/permissions using a constrained ephemeral container.
5. Confirm Traefik and the Authentik outpost share the configured network.

For Bearer-API-only deployments, set `SAVE_SYNC_PANEL_MODE=disabled`. This disables the browser panel rather than exposing an anonymous panel.

**Do not place SQLite on NFS/SMB and do not put the storage volume under a web document root.**

Save Sync v2 must not be pointed directly at a legacy Palworld Sync v1 database. The application detects the incompatible layout and fails explicitly; keep the old service/volume or initialize v2 separately.

## Important environment variables

| Variable | Purpose |
|---|---|
| `SAVE_SYNC_GAME_KEY` | Adapter/deployment key |
| `SAVE_SYNC_GAME_CONFIG_PATH` | Game descriptor inside the container |
| `SAVE_SYNC_CONTAINER_NAME` | Unique web-backend container name |
| `SAVE_SYNC_BACKUP_CONTAINER_NAME` | Unique backup-supervisor container name |
| `SAVE_SYNC_HOST_STORAGE_PATH` | Private absolute storage directory on the host |
| `SAVE_SYNC_STORAGE_PATH` | Internal mount, normally `/data/save-sync` |
| `SAVE_SYNC_DB_PATH` | SQLite database inside the mount |
| `SAVE_SYNC_PUBLIC_HOST` | Traefik host rule |
| `SAVE_SYNC_PUBLIC_BASE_URL` | HTTPS URL used by verification |
| `SAVE_SYNC_PUBLIC_ROOT` | Public tree that storage must never overlap |
| `SAVE_SYNC_PROXY_NETWORK` | External Docker network shared with Traefik |
| `SAVE_SYNC_AUTHENTIK_FORWARD_AUTH_URL` | Internal ForwardAuth endpoint |
| `SAVE_SYNC_PANEL_MODE` | `authentik` or `disabled` |
| `SAVE_SYNC_TRAEFIK_CERT_RESOLVER` | Existing Traefik TLS resolver |
| `SAVE_SYNC_WEB_USERS` | `username:role` allowlist; bootstrap-only when the game enables `managedHosts` |
| `SAVE_SYNC_USER_IDENTITIES_JSON` | Display names/retention slots; bootstrap-only when the game enables `managedHosts` |
| `SAVE_SYNC_MAX_UPLOAD_SIZE` | Maximum ZIP size |
| `SAVE_SYNC_LOCK_TTL_SECONDS` | Lock TTL; default 300 |
| `SAVE_SYNC_HEARTBEAT_INTERVAL_SECONDS` | Recommended client heartbeat; default 60 |
| `SAVE_SYNC_RETENTION_PER_SLOT` | Versions retained per slot; default 1 |
| `SAVE_SYNC_POST_PUBLISH_COMMAND` | Backup command consumed by the durable supervisor |
| `SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS` | Timeout for one attempt; default 1800 |
| `SAVE_SYNC_BACKUP_POLL_SECONDS` | SQLite queue polling interval; default 1 |
| `SAVE_SYNC_PROXY_SECRET` | Internal proxy/backend secret |
| `SAVE_SYNC_CSRF_SECRET` | Panel CSRF signing secret |

The two final secrets must be independent, random values of at least 32 characters and must never appear in logs or Git.

When `game.json` enables `managedHosts`, `SAVE_SYNC_WEB_USERS` and `SAVE_SYNC_USER_IDENTITIES_JSON` seed users that do not already exist. Schema 4 then makes the database authoritative for subsequent role, display-name, slot and enabled/disabled changes, so restarting the container does not overwrite panel-managed access. Authentik still authenticates the username; Save Sync decides whether that username is active and which computers it may use. With `managedHosts` disabled, as in Palworld, the existing config-managed access behavior is preserved.

For games with `managedHosts` enabled, administrators can manage users, computers and computer-bound API tokens from `/games/<gameKey>`. Register each physical PC with a unique stable `ClientId`, then create a token for that computer and put that token only on that PC. Managed lock acquisition requires a computer-bound token whose registered `ClientId` exactly matches the client request. Legacy unbound tokens remain visible for migration/administration but cannot start a managed game session and should be rotated.

The experimental Valheim descriptor enables `managedHosts`. Deploy it with its own database/storage and follow [VALHEIM.md](VALHEIM.md). Palworld leaves `managedHosts` disabled and retains the stable config-managed token/user behavior.

## Durable external backup and retention

Publication and queue insertion are a single SQLite transaction. Gunicorn does not launch the external command.

The `backup-supervisor` service:

1. claims a pending version and refreshes `started_at`;
2. audits `backup_hook_started`;
3. runs `SAVE_SYNC_POST_PUBLISH_COMMAND` in an isolated process group with `SAVE_SYNC_PUBLISHED_VERSION`, `SAVE_SYNC_PUBLISHED_PATH`, `SAVE_SYNC_PUBLISHED_IDENTITY` and the timeout in its environment;
4. terminates the whole process group on timeout;
5. transactionally records the final result, removes the queue row and commits retention **metadata**;
6. revalidates current references in a second phase before unlinking obsolete ZIP files.

Pending versions are protected beyond the normal retention limit. This is intentional: **backup safety wins over the configured count**.

The backup command must stay in the **foreground** until the real backup has finished. Do not hide the actual work behind `&`, `nohup`, another daemon or any wrapper that exits early.

The supervisor provides **at-least-once** execution after uncertain crashes. Use an idempotent command or one that safely tolerates repetition, such as `restic backup`.

A known non-zero exit code or observed timeout is recorded as a final failed attempt. An uncertain crash before that result reaches SQLite is retried.

### Restic build

The image includes **restic 0.18.0** from official release assets, pinned by version and SHA-256 for both `amd64` and `arm64`. CI verifies the installed binary. It is deliberately not installed from an unpinned OS package repository.

Example:

```dotenv
SAVE_SYNC_POST_PUBLISH_COMMAND=restic backup /data/save-sync --exclude /data/save-sync/temporary
```

Configure the restic repository/password through deployment secrets. The cache lives under `/data/save-sync/temporary` and should be excluded.

### Operating the supervisor

```bash
docker compose ps backup-supervisor
docker compose logs --tail=100 backup-supervisor
```

The supervisor healthcheck verifies a recent heartbeat, exactly the supported SQLite schema and access to required tables. If work is pending while `SAVE_SYNC_POST_PUBLISH_COMMAND` is empty, the service becomes unhealthy because the queue cannot make progress.

Do not manually delete `pending_backups` as normal recovery. Fix the supervisor/backup command or make an explicit administrative decision about the protected version.

### Database backup consistency

Backing up the immutable published ZIP is strong and straightforward. Backing up a live SQLite WAL directory with `restic backup /data/save-sync` is **not** automatically a transactionally consistent database snapshot.

For disaster recovery of SQLite itself, use the SQLite Backup API or stop the service during the volume backup. Example:

```bash
python3 - /path/save-sync.sqlite3 /path/backup.sqlite3 <<'PY'
import sqlite3
import sys
source, target = sys.argv[1:]
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
print(sqlite3.connect(target).execute("PRAGMA integrity_check").fetchone()[0])
PY
```

Store the resulting backup outside public storage with mode `0600`.

## Deployment

```bash
config/deploy.sh
```

The script validates `.env`, renders the private Traefik route, runs `docker compose config`, builds the image, prepares storage and starts both backend and durable supervisor. Before publishing the route it verifies:

- backend healthy;
- `backup-supervisor` healthy;
- no unexpected public host ports;
- anonymous API returns `401`;
- anonymous panel redirects to login when the panel is enabled.

The route is published only after those checks pass.

For an isolated local validation, use [LOCAL-DEVELOPMENT.md](LOCAL-DEVELOPMENT.md).

## First API token

The preferred bootstrap is to sign into the protected panel as an administrator and create one token per machine. Plaintext is shown once.

`SAVE_SYNC_BOOTSTRAP_TOKENS_JSON` exists for controlled initial bootstrap only. Remove it from the environment after initialization; SQLite stores token hashes but `.env` contains plaintext while the bootstrap variable remains.

## Rollback

```bash
config/rollback.sh
```

Rollback restores the previous Traefik route when available and stops both backend and supervisor without deleting data. It does not automatically downgrade a database schema.

To restore an incompatible older image:

1. make a consistent backup of current state;
2. remove the public route;
3. stop the stack;
4. move the live database and `-wal`/`-shm` sidecars out of the way;
5. restore a matching SQLite snapshot to a temporary file on the same filesystem, fsync it and publish it atomically;
6. do not reuse WAL sidecars from another run;
7. start the older image and verify it before reopening the route.

## Common incidents

### Backup supervisor is degraded

If `/backup-status` remains `pending` or `stalePending` unexpectedly:

```bash
docker compose ps backup-supervisor
docker compose logs --tail=200 backup-supervisor
```

Do not delete the pending ZIP. Once the supervisor is healthy again, work with no known final result is reclaimed automatically.

### Lock remains after a host crash

Wait for the TTL and check `status`. If a clock/state problem keeps the lock around, an administrator may use `force-unlock` with an audited reason. Never force-unlock while the other server might still be running.

### Upload response was lost

The Windows client reconciles using remote version, SHA-256, identity and actor. If it cannot prove publication, it preserves the ZIP under `client/data/pending-uploads` and keeps `pending-session.json`. Never edit `baseVersion` manually.

### Several local worlds exist

The Palworld adapter prefers the remote `worldGuid` when its folder exists. During first initialization, configure `InitialWorldGuid` or leave exactly one unambiguous candidate. Other local worlds are not deleted automatically.

### Heartbeat is degraded

After repeated failures the client stops the game-server/writer process through the adapter's controlled shutdown path and does not automatically publish uncertain progress. Palworld uses its REST save/shutdown flow; experimental Valheim uses CTRL+C plus process-exit/final-generation validation. This deliberately avoids continuing a game session without reliable exclusion.
