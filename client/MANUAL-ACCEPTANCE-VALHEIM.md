# Manual Valheim acceptance test

This checklist is for the experimental Valheim 1.0 Windows adapter. Run it across four disposable/test hosts when the intended deployment has four possible server PCs. Keep an independent copy of the world outside Save Sync. **Never use the only valid copy of a world for acceptance testing.**

## Preconditions

- All four hosts use the exact same repository commit/client artifact.
- Each host has its own Save Sync token and distinct `ClientId`.
- Each physical PC is registered and enabled in the web panel, and each new token is bound to the matching registered computer.
- The backend is an isolated `SAVE_SYNC_GAME_KEY=valheim` deployment with its own storage and SQLite database.
- `config.valheim.example.json` has been copied to `config.json` and the paths/world name adjusted.
- The selected world uses Valheim 1.0 folder-based saves under `worlds_local/<WorldName>`.
- A verified external backup exists.
- No `valheim_server.exe` process is running.

## Host A initializes the authority

1. Run `Configure-Secrets.cmd`, then `Test-Connection.cmd`.
2. Confirm the client reports the expected embedded world name and World UID.
3. Start with `Start-ValheimSync.cmd`.
4. Confirm the client waits until the dedicated-server log contains `Game server connected` before reporting the server active.
5. Join the server and make an identifiable world change.
6. Return to the Save Sync console and press ENTER.
7. Confirm the client sends CTRL+C, waits for `valheim_server.exe` to exit and reads a complete committed generation before archiving.
8. Confirm upload creates remote version 1 and removes `data/valheim/pending-session.json`.

## Hosts B, C and D advance the same authority

1. Confirm Host B cannot start while Host A owns the lock.
2. After Host A publishes, start Host B through `Start-ValheimSync.cmd`.
3. Confirm the remote ZIP is verified and installed by replacing the whole configured world directory, not merging files.
4. Join the server and confirm Host A's change exists.
5. Make a second identifiable change, press ENTER in the Save Sync console and confirm version 2 is published.
6. Start Host C, confirm Host B's change exists, make a third identifiable change and publish version 3.
7. Start Host D, confirm Host C's change exists, make a fourth identifiable change and publish version 4.
8. Start Host A again and confirm Host D's change exists before making any further change.

At every hand-off, open `/games/valheim` and confirm the panel reports the correct current version, last user/computer and lock owner. While one host owns the lock, each of the other three must be rejected if it attempts to start.

## Managed-access checks

- Try a valid computer-bound token with another registered `ClientId`; lock acquisition must be rejected.
- Disable one inactive computer from the panel and confirm its token can no longer start a session.
- Re-enable it, create a replacement token and confirm the new token works only with that computer.
- While a host owns the lock, disable that host. Its next heartbeat must fail and the client must stop Valheim cleanly; the lock must remain occupied until its TTL expires or an administrator deliberately force-unlocks it.
- Confirm a computer-bound token owned by an administrator cannot call administrative API endpoints.
- Confirm the panel's recent audit identifies lock/publication activity by user and `ClientId`.

## Failure cases

- Close/terminate `valheim_server.exe` outside the controlled Save Sync CTRL+C path. The client must leave a pending session and must **not** upload automatically.
- Prevent the server from exiting after CTRL+C. The client must time out without forcing the process and without creating a publication archive.
- Interrupt the network after the local ZIP is created. The ZIP must remain under `data/valheim/pending-uploads` when publication cannot be reconciled.
- Attempt to install an archive with a different World UID. The configured world must remain unchanged.
- Put an obsolete chunk in the target world before a remote install. The obsolete file must disappear because restore uses directory replacement rather than merge.
- Restore an old server-side version administratively. Restore must create a new higher version.

## Evidence to record

Record the commit, adapter version, Valheim version, PASS/FAIL, remote version numbers, World UID consistency, and whether CTRL+C shutdown completed. Do not publish tokens, passwords, real save archives, personal paths, server addresses or complete logs.
