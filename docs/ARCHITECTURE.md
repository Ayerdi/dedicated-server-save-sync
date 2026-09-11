# Architecture and invariants

This document describes the safety properties that define Save Sync. They are more important than any individual implementation detail.

## Code organization

The Flask application is composed from small modules with explicit responsibilities:

- `save_sync/app.py` is the Flask composition/HTTP layer: configuration, authentication, request/response translation and service wiring;
- `save_sync/database.py` owns the SQLite connection policy, schema, migrations and bootstrap;
- `save_sync/domain.py` defines transport-agnostic domain errors used by the HTTP layer and services;
- `save_sync/sessions.py` owns lock acquisition, heartbeat/unlock and managed-host session revalidation;
- `save_sync/publications.py` owns ZIP staging/validation, atomic publication and two-phase historical restore;
- `save_sync/game_config.py` loads and validates per-game identity/capability configuration;
- `save_sync/identities.py` parses user display/retention identities shared by the web application and backup supervisor;
- `save_sync/managed.py` registers the opt-in managed-user/computer endpoints used only when `managedHosts: true`;
- `save_sync/admin.py` registers generic administrative endpoints such as tokens, audit and force-unlock;
- `save_sync/panels.py` contains the managed and legacy panel templates and panel route wiring;
- `save_sync/retention.py` contains retention/reconciliation primitives;
- `save_sync/backup_supervisor.py` owns the independent durable backup worker.

Game adapters remain outside the backend under `client/adapters/<game>/`. The backend never imports game-specific save parsers. Palworld keeps the unmanaged compatibility surface, while games such as Valheim can opt into managed computers through configuration.

## Sources of authority

`versions.version` defines progress order. **File timestamps never do.** `current_save` points to one immutable published version.

The first successful publication fixes the authoritative `saveIdentity`. Every later publication must match it.

A valid publication requires all of the following at the same time:

- an active token for the user that acquired the lock;
- the matching opaque `sessionId`;
- an unexpired lock;
- `baseVersion` equal to the current authoritative version;
- an adapter-valid identity equal to the authoritative save identity;
- a ZIP that passes structure limits and server-side SHA-256 verification.

## Session state machine

```text
uninitialized (v0, identity null)
  └─ lock base0 + valid upload → initialized (v1, identity fixed)

available
  └─ lock → occupied
       ├─ heartbeat → occupied with a refreshed expiry
       ├─ valid upload → new version + available
       ├─ owner unlock → available
       └─ TTL expires → available at the next transactional access
```

`sessionId` is returned only when a lock is acquired. It is not exposed later through status, the UI or audit records.

## Atomic publication

Locks, uploads, restores and retention metadata changes use `BEGIN IMMEDIATE`.

A publication follows this order:

1. receive the upload into private temporary storage;
2. calculate SHA-256 and validate the ZIP defensively;
3. inside the write transaction, re-check the authoritative identity and base version, then the lock/session plus current user/token/host authorization for managed deployments;
4. publish the ZIP under an immutable historical name with `os.replace`;
5. sync the containing directory;
6. insert the new version and move `current_save`;
7. when external backup is enabled, insert the version into `pending_backups` **in the same SQLite transaction**;
8. release the session lock and commit SQLite;
9. reconcile retention metadata without touching pending backup versions;
10. in a second phase, revalidate filesystem references before deleting unreferenced ZIPs.

An exception before commit leaves the previous authoritative version in place. A crash after the database commit may leave an orphan file, which is safe and can be reconciled later.

Historical restore deliberately uses two write transactions. The first verifies that no lock exists and snapshots the source/current metadata; the source ZIP is then copied and hashed outside any SQLite write lock. A second `BEGIN IMMEDIATE` re-checks the lock, current version, source metadata and identity immediately before publishing the restored copy as a new immutable version. This avoids holding the database write lock during a potentially large file copy without weakening the final race checks.

## Durable backup supervisor

Gunicorn never owns the lifetime of external backup commands in production. A separate Compose service, `backup-supervisor`, shares the private storage and SQLite database.

The supervisor:

1. claims a row from `pending_backups` and refreshes `started_at`;
2. records `backup_hook_started`;
3. launches the configured command in a separate process group;
4. enforces the configured timeout and escalates `SIGTERM` to `SIGKILL` for the whole group when necessary;
5. in one write transaction, removes the pending row, records success/failure and applies **retention metadata**;
6. after that transaction commits, takes a second write lock, re-reads current references and unlinks only ZIPs that are still unreferenced.

This two-phase delete rule prevents the dangerous ordering where a ZIP disappears and then SQLite rolls back to metadata that still references it. The safe failure mode is the opposite: a crash may leave an extra orphan ZIP, which reconciliation can remove later.

### At-least-once semantics

A controlled supervisor stop terminates its child process but deliberately leaves the queue row. A hard crash also leaves the row in SQLite. On restart, the work is claimed again.

Therefore the external backup command must be idempotent or tolerate repetition. A known non-zero exit code or an observed timeout is a final failed attempt and is audited; an uncertain crash before recording the outcome is retried.

A singleton `flock` prevents two supervisors from consuming the same storage concurrently.

## Concurrency and schema

- SQLite uses WAL mode and `busy_timeout`.
- Schema creation/migration is protected by a multiprocess `flock`.
- `PRAGMA user_version=4` identifies the supported schema.
- A newer schema is rejected rather than implicitly downgraded.
- Two simultaneous lock acquisitions produce one winner.
- Two uploads based on the same version cannot both publish.
- Backup queue insertion and publication share one SQLite commit, so a confirmed version cannot require backup without having been queued.

When a game configuration opts in with `managedHosts: true`, managed access separates people from machines. `users` represent identities authenticated by Authentik; `authorized_hosts` represent concrete computers through a stable `clientId`. A computer-bound Bearer token is valid only for its assigned active host and never grants administrative API privileges, even when the owning user is an administrator. Disabling a host does not delete an active lock: the client fails its next authenticated heartbeat and stops, while the lock remains until normal expiry or an explicit administrative force-unlock. The experimental Valheim configuration enables this capability; Palworld leaves it disabled so its stable UI and client authorization flow are unchanged.

Each deployment manages one `gameKey` and uses one database and storage root. Another game must use another isolated Compose project/volume in this reference architecture.

## Save identity

`config/games/{gameKey}.json` declares the identity field, label, regex and normalization rules. The backend stores the canonical value in `save_identity` and may also expose the adapter-specific field.

Palworld uses:

```text
identityField: worldGuid
pattern:       ^[A-F0-9]{32}$
normalization: uppercase
```

The backend does not parse `Level.sav`; the Palworld adapter is responsible for obtaining the real game identity correctly.

Historical restore preserves the same identity and publishes a **new version**. There is no normal endpoint for replacing the authoritative world with a different identity.

## Trust boundaries

- Traefik strips identity headers supplied directly by clients.
- Authentik protects the browser panel.
- The proxy injects its internal secret only after successful ForwardAuth.
- Windows clients authenticate with independent Bearer tokens.
- Palworld's local REST API uses separate credentials and must stay on localhost.
- SQLite and ZIP storage is never served by the web frontend.
- `backup-supervisor` has no public HTTP port and is not connected to Traefik.

## Retention

Users are mapped to retention slots through `SAVE_SYNC_USER_IDENTITIES_JSON`. `SAVE_SYNC_RETENTION_PER_SLOT` keeps the newest N versions for each slot. Aliases for the same physical host should share a slot.

Versions listed in `pending_backups` are retained in addition to the normal limit until the supervisor records a final result.

See [MIGRATIONS.md](MIGRATIONS.md) for schema policy and [OPERATIONS.md](OPERATIONS.md) for deployment and backup procedures.
