# Architecture and safety model

`v2.2.2` remains the stable Palworld release. The current `main` backend is internally modular and also supports the experimental Valheim adapter through per-game capabilities.

## Backend modules

- `save_sync/app.py` — Flask composition, HTTP/authentication and service wiring;
- `save_sync/database.py` — SQLite connection policy, schema and migrations;
- `save_sync/sessions.py` — lock, heartbeat, unlock and managed-host revalidation;
- `save_sync/publications.py` — upload validation, atomic publication and historical restore;
- `save_sync/game_config.py` — per-game identity/capability configuration;
- `save_sync/managed.py` — opt-in users/computers management;
- `save_sync/admin.py` — tokens, audit and force-unlock;
- `save_sync/panels.py` — browser panel variants;
- `save_sync/retention.py` — retention/reconciliation;
- `save_sync/backup_supervisor.py` — durable external-backup worker.

This is one application, not a microservice split. The modules exist to keep transactional boundaries explicit.

## Authority

The database owns monotonically increasing `version` numbers. `current_save` points at one immutable published ZIP. File timestamps are never version authority.

Every adapter supplies a canonical `saveIdentity`:

- Palworld: `worldGuid`;
- experimental Valheim: signed 64-bit `worldUid`.

A publication must match the current identity, current `baseVersion` and valid lock/session at the same time.

## Atomic publication

The upload is staged and validated before a `BEGIN IMMEDIATE` transaction rechecks identity, version, lock/session and current authorization. The immutable ZIP, `versions`, `current_save`, backup queue and lock release are committed as one authority change.

Unexpected exceptions roll back. Expected domain rejections preserve the same audited rejection behavior as the pre-refactor routes.

## Restore

Historical restore intentionally uses two write transactions: snapshot/revalidate first, copy+hash outside the write lock, then revalidate everything immediately before publishing the restored ZIP as a **new higher version**.

## Managed computers

Games with `managedHosts: true` separate users from physical PCs. A host-bound token must still belong to the active user, exact registered host and exact `ClientId` when the write transaction executes. See [[Managed-Computers]].

## Client safety

The game/server writer must stop before the save is archived. Palworld uses its local REST save/shutdown flow. Experimental Valheim uses CTRL+C, waits for process exit and validates a final complete generation.

Valheim also reserves enough lock lifetime for a controlled shutdown. Expired TTL alone is never proof that a failed/stranded old server process has stopped.

For deeper implementation detail see [docs/ARCHITECTURE.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/docs/ARCHITECTURE.md).

[[Arquitectura|Leer en español]]

