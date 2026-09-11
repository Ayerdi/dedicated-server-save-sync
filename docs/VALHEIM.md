# Experimental Valheim adapter

> **Development-tree feature.** Valheim support is present on `main` after `v2.2.2`; it is not part of the stable `v2.2.2` Palworld release. Use an isolated test world and independent backup until the real four-host acceptance checklist has passed for your environment.

The Valheim adapter reuses the same authoritative-version, lock, heartbeat, history and atomic-publication backend as Palworld, but its client lifecycle is game-specific. It works with Valheim 1.0 folder-based worlds under `worlds_local/<WorldName>` and identifies the save by the intrinsic signed 64-bit World UID stored in the committed `.fwl2` generation metadata.

## Isolation requirements

Run Valheim as its own Save Sync deployment:

- `SAVE_SYNC_GAME_KEY=valheim`;
- `SAVE_SYNC_GAME_CONFIG_PATH=/app/config/games/valheim.json` or the equivalent mounted path;
- a dedicated SQLite database;
- a dedicated storage root/volume;
- a distinct Compose project/container naming set when Palworld is deployed on the same host.

Never point the Valheim deployment at the Palworld database or ZIP storage.

## Managed computers

`config/games/valheim.json` enables `managedHosts`.

Before a client can acquire a Valheim lock:

1. the Authentik/Save Sync user must exist and be active;
2. the physical PC must be registered in the Valheim web panel with a stable `ClientId`;
3. an API token must be created for that exact registered computer;
4. the client `config.json` must use the same `ClientId`.

The token is sync-only. A computer-bound token cannot perform administrative API operations even when its owning user has the `admin` role.

Disabling the user, token or host prevents further trusted session activity. An existing lock is deliberately not deleted automatically: the client fails closed, stops the server cleanly when possible, and the lock remains until TTL expiry or an explicit administrator force-unlock.

## Windows client setup

Valheim is not in the `v2.2.2` release ZIP. For development testing, use a client checkout/artifact built from the same tested `main` commit as the backend.

1. Copy `client/config.valheim.example.json` to `client/config.json`.
2. Set `PlayerName` to the Save Sync display identity expected by the backend.
3. Set a stable per-PC `ClientId` matching the registered computer.
4. Set `ApiBaseUrl` to `/api/games/valheim` on the isolated Valheim backend.
5. Configure `ServerRoot`, `ServerExecutable`, `SaveRoot`, `WorldName`, `ServerName` and `ServerPort`.
6. Run `Configure-Secrets.cmd` and enter that PC's host-bound Save Sync token plus the Valheim dedicated-server password.
7. Run `Test-Connection.cmd`.
8. Start through `Start-ValheimSync.cmd`; do not start `valheim_server.exe` independently for a synchronized session.

Valheim secrets are stored under `client/data/valheim/secrets.json` using Windows DPAPI `CurrentUser`. Treat that file as local per-host state and provision separate credentials on each PC instead of copying it between machines.

## Save model

The adapter treats the complete configured world directory as one save unit. A valid committed generation requires the matching set:

```text
_main.<generation>.fwl2
_main.<generation>.db2
_main.<generation>.chunks
_main.<generation>.ok
*.chunk
```

The adapter selects the highest complete generation, verifies that complete generations agree on one World UID, and archives the whole world directory. Download installation uses staged directory replacement with rollback rather than merging files into an existing world; stale chunks therefore cannot survive a successful replacement.

The authoritative `saveIdentity` is `worldUid`, not a directory timestamp or hash.

## Session lifecycle

```text
status
  -> acquire host-bound lock
  -> start heartbeat
  -> download/install authoritative save if needed
  -> local recovery backup
  -> start valheim_server.exe
  -> wait for "Game server connected"
  -> play while heartbeat remains reliable
  -> CTRL+C controlled shutdown
  -> wait for process exit + post-exit grace
  -> verify final committed generation
  -> ZIP + SHA-256
  -> upload against lock baseVersion/worldUid
```

The adapter reserves enough lock lifetime for one heartbeat request plus the configured clean-shutdown timeout, post-exit grace and a safety margin. If the remaining lease enters the clean-shutdown reserve, the client fails closed rather than risking a second host becoming eligible while the first server is still shutting down.

An unexpected `valheim_server.exe` exit is not automatically published.

## Recovery rules

- If the network fails before a session modifies the world, the client may release the lock normally.
- Once a server session has been entered, an unconfirmed publication leaves the session pending and does not automatically release the lock early.
- If upload response delivery is ambiguous, the client reconciles against remote status before deciding whether publication succeeded.
- If publication cannot be confirmed, the final ZIP is preserved under `data/valheim/pending-uploads` for manual recovery.
- Do not delete `pending-session.json` or a pending upload merely to make the next run proceed. First determine whether the remote version advanced and which copy is authoritative.

## Acceptance before real-world use

CI proves serialization, API contracts, failure paths and PowerShell helper behavior; it cannot prove a real Valheim server's save/shutdown semantics on your machines.

Run [the four-host acceptance checklist](../client/MANUAL-ACCEPTANCE-VALHEIM.md) with a disposable/independently backed-up world. The intended hand-off is A → B → C → D → A, including lock rejection, world replacement, clean shutdown, disabled-host behavior and recovery scenarios.

Do not use the only valid copy of a real world as the acceptance-test input.

## Relevant implementation references

- `config/games/valheim.json` — identity/capability descriptor;
- `client/config.valheim.example.json` — client configuration template;
- `client/adapters/valheim/Adapter.ps1` — Windows lifecycle implementation;
- `client/adapters/valheim/tests/Adapter.Tests.ps1` — adapter regression tests;
- `save_sync/sessions.py` — lock and managed-host revalidation;
- `save_sync/publications.py` — publication and restore safety;
- [Architecture](ARCHITECTURE.md) — backend invariants;
- [Operations](OPERATIONS.md) — deployment, backups and managed access.
