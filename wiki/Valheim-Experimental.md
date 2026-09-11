# Experimental Valheim support

> **Not part of stable v2.2.2.** The Valheim 1.0 adapter is available on the `main` development tree. Test it with an isolated, independently backed-up world before considering real use.

Valheim uses the same authoritative version, lock, heartbeat, history and recovery model as the stable Palworld backend, but the Windows adapter controls a different server/save lifecycle.

## What is different

- saves live under `worlds_local/<WorldName>`;
- Save Sync treats the whole configured world directory as one save unit;
- the authoritative identity is the intrinsic signed 64-bit `worldUid` read from committed `.fwl2` metadata;
- the adapter starts `valheim_server.exe` itself;
- clean shutdown is requested with CTRL+C;
- publication happens only after the process exits and a complete final generation is verified;
- Valheim enables [[Managed-Computers]] and therefore requires a token bound to the registered physical PC.

## Safe setup

1. Deploy Valheim with its own `gameKey=valheim`, SQLite database and storage root. Never share Palworld storage/database.
2. Register every possible host PC in the Valheim panel with a unique stable `ClientId`.
3. Create a separate computer-bound token for each PC.
4. On each PC, copy `client/config.valheim.example.json` to `client/config.json` and set the matching `ClientId`, paths, world and server settings.
5. Run `Configure-Secrets.cmd` and enter that PC's token plus the Valheim server password.
6. Run `Test-Connection.cmd`.
7. Start only through `Start-ValheimSync.cmd` for synchronized sessions.

Valheim is not included in the stable v2.2.2 client package. Use backend and client from the same tested development commit/artifact.

## Session safety

The client acquires the remote lock before touching the authoritative save, maintains heartbeats while Valheim is running and reserves enough lock lifetime for a controlled shutdown. If the lease becomes unreliable, it fails closed and attempts to stop Valheim while another host is still excluded.

An unexpected server exit is **not** published automatically.

If an upload cannot be confirmed, the final ZIP is preserved under `data/valheim/pending-uploads` and the pending session is kept for recovery.

If shutdown failed or a session is left pending, **TTL expiry is not proof that the old `valheim_server.exe` stopped**. Before another host starts, confirm the previous writer process is gone and review the pending state.

## Before using a real world

Run the [four-host A → B → C → D → A acceptance checklist](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/client/MANUAL-ACCEPTANCE-VALHEIM.md). It covers lock exclusion, remote replacement, clean shutdown, disabled-host behavior and failure recovery.

Do not use the only valid copy of a real world as the acceptance-test input.

## More detail

- [Full Valheim technical guide](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/docs/VALHEIM.md)
- [[Managed-Computers]]
- [[Architecture]]
- [[Troubleshooting]]
- [[Inicio|Español]]
