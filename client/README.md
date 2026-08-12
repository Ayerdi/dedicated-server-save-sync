# Save Sync Windows client

`SyncGame.ps1` is the common Windows PowerShell 5.1 launcher. It reads `Adapter` and `GameKey`, validates the adapter manifest and hands control to `adapters/<adapter>/Adapter.ps1`. Machine-specific values live only in `config.json` and DPAPI-protected secrets.

> **Stable scope:** product release `v2.2.2` supports Palworld. Adapter abstractions remain because they are part of the architecture, but new games and the future multi-game/device-sync redesign are outside this repository's maintenance roadmap.

## Product version vs client version

Two version numbers exist intentionally:

- `v2.2.2`: product release covering backend, packaged client, docs and release process;
- `clientVersion=1.2.0`: the Palworld adapter/client component version written to ZIP manifests and diagnostics.

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

The older `Configurar-secretos.cmd`, `Probar-conexion.cmd` and `Iniciar-PalworldSync.cmd` names remain as compatibility aliases.

Do not copy `data/secrets.json` between machines. DPAPI binds it to the Windows user and machine that created it.

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

## Normal use

Launch `Start-PalworldSync.cmd`. Do not start `PalServer.exe` independently.

The client acquires the remote lock, downloads the authoritative version when necessary, starts PalServer and heartbeats the session. On shutdown it asks Palworld to save and stop, verifies the writer has exited, builds the ZIP and uploads it with the `baseVersion` acquired at lock time.

If the client repeatedly loses remote exclusion, it stops PalServer rather than continuing without reliable ownership.

## Recovery files

Files under `data/` include:

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

CI cannot prove Palworld's real REST behavior or semantic world consistency. Use [MANUAL-ACCEPTANCE.md](MANUAL-ACCEPTANCE.md) for a controlled two-host regression test.
