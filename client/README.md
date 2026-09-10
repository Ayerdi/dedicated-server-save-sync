# Save Sync Windows client

`SyncGame.ps1` is the common Windows PowerShell 5.1 launcher. It reads `Adapter` and `GameKey`, validates the adapter manifest and hands control to `adapters/<adapter>/Adapter.ps1`. Machine-specific values live only in `config.json` and DPAPI-protected secrets.

> **Stable scope:** product release `v2.2.2` supports Palworld. The development tree also contains an experimental Valheim 1.0 Windows adapter; it is not part of the `v2.2.2` support promise and must pass its real two-host acceptance checklist before production use.

## Product version vs client version

Two version numbers exist intentionally:

- `v2.2.2`: product release covering backend, packaged client, docs and release process;
- `clientVersion=1.2.0`: the Palworld adapter/client component version written to ZIP manifests and diagnostics;
- `clientVersion=0.1.0`: the initial experimental Valheim adapter version.

The backend does not infer compatibility from `clientVersion`. In production, deploy backend and client from the **same product release**.

## Installation

1. Download the `v2.2.2` client ZIP and its `.sha256` file from Releases.
2. Verify the checksum before extracting it.
3. Copy `config.example.json` to `config.json`.
4. Set `Adapter`, `GameKey`, `PlayerName`, `ClientId`, public API URL and game paths.
5. Enable Palworld's REST API on **localhost only** and configure its `AdminPassword`.
6. Run `Configure-Secrets.cmd`.
7. Run `Test-Connection.cmd`.
8. Start sessions with `Start-PalworldSync.cmd`.

For experimental Valheim testing, copy `config.valheim.example.json` to `config.json`, configure the dedicated-server paths and `WorldName`, run the same secret/connection helpers, then start with `Start-ValheimSync.cmd`. Valheim credentials are stored separately under `data/valheim/`.

For a multi-PC Valheim group, register every possible server PC from the Save Sync web panel first. Give each machine a distinct stable `ClientId` and its own computer-bound token; four or more PCs may alternate against the same authoritative world, but the global lock permits only one active server session at a time.

The older `Configurar-secretos.cmd`, `Probar-conexion.cmd` and `Iniciar-PalworldSync.cmd` names remain as compatibility aliases.

Do not copy DPAPI secret files between machines: Palworld uses `data/secrets.json` and Valheim uses `data/valheim/secrets.json`. DPAPI binds them to the Windows user and machine that created them.

## Important configuration fields

- `PlayerName`: must match the display identity configured on the backend.
- `ClientId`: stable, non-secret identifier for this PC.
- `Adapter`: integration directory; the stable release includes `palworld`.
- `GameKey`: must match `adapter.json` and the deployed backend.
- `ApiBaseUrl`: ends in `/api/games/<gameKey>` and must use HTTPS in production.
- `PalServerRoot` / `PalServerExecutable`: dedicated-server installation.
- `SaveGamesRoot`: parent of `0/<worldGuid>`.
- `GameUserSettingsPath`: file containing `DedicatedServerName`.
- `InitialWorldGuid`: used only to disambiguate the first upload; it may be empty after initialization.
- `RestApiBaseUrl`: must point to localhost.
- `HeartbeatSeconds`: must be clearly shorter than the backend lock TTL.
- `LocalBackupRetention`: number of local pre-session/download backup ZIPs.

Valheim uses `ServerRoot`, `ServerExecutable`, `SaveRoot`, `WorldName`, `ServerName`, `ServerPort` and `StartupTimeoutSeconds`. `SaveRoot` is the Valheim data root that contains `worlds_local`; the adapter treats the entire `worlds_local/<WorldName>` directory as one save unit. Its authoritative `saveIdentity` is the intrinsic signed 64-bit World UID read from `_main.<generation>.fwl2`, not a timestamp or directory hash. Startup is confirmed from Valheim's own `Game server connected` log marker before the session is presented as ready.

## Normal use

Launch `Start-PalworldSync.cmd`. Do not start `PalServer.exe` independently.

The client acquires the remote lock, downloads the authoritative version when necessary, starts PalServer and heartbeats the session. On shutdown it asks Palworld to save and stop, verifies the writer has exited, builds the ZIP and uploads it with the `baseVersion` acquired at lock time.

If the client repeatedly loses remote exclusion, it stops PalServer rather than continuing without reliable ownership.

The Valheim adapter follows the same lock/heartbeat rules, but its shutdown path is deliberately stricter: it starts `valheim_server.exe` in an isolated hidden console, sends CTRL+C to that console, waits for the process to exit, verifies a complete Valheim 1.0 generation and only then archives. An unexpected process exit is left pending and is never published automatically.

## Recovery files

Palworld stores these under `data/`; Valheim stores the equivalent files under `data/valheim/`:

- `state.json`: last confirmed remote version;
- `pending-session.json`: locally modified session not yet confirmed remotely;
- `pending-uploads/`: ZIPs whose publication could not be confirmed;
- `backups/`: local copies taken before download/session changes;
- `logs/`: diagnostic output designed to exclude tokens and passwords.

If a pending session exists, do not start the other host. Check the current remote version, preserve the pending ZIP and never edit `baseVersion` to bypass a conflict.

## Multi-world safety

When several local Palworld worlds exist, the client prefers the `worldGuid` already recorded by the backend when that folder exists. An uninitialized backend requires either `InitialWorldGuid` or one unambiguous local world. Other worlds are never deleted automatically.

## Tests

```powershell
Invoke-Pester -Path .\client -CI
```

CI cannot prove a real game server's save/shutdown semantics. Use [MANUAL-ACCEPTANCE.md](MANUAL-ACCEPTANCE.md) for Palworld and [MANUAL-ACCEPTANCE-VALHEIM.md](MANUAL-ACCEPTANCE-VALHEIM.md) for the experimental Valheim adapter.
