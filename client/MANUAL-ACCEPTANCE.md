# Manual Palworld acceptance test

Run this test on two disposable/test Windows hosts before publishing a release that changes client behavior. Use independent external backups and an isolated Save Sync deployment. **Never experiment on the only valid copy of a world.**

## Preparation

- [ ] Both hosts use the exact same client artifact/commit.
- [ ] Each host has its own token and distinct `ClientId`.
- [ ] Palworld REST listens on localhost only.
- [ ] A verified external copy of the world exists.
- [ ] No `PalServer.exe` process is running.

## Host A

1. Run `Configure-Secrets.cmd` and `Test-Connection.cmd`.
2. Start with `Start-PalworldSync.cmd`.
3. Confirm the client acquires the lock and selects the expected `worldGuid`.
4. Join the game, make an identifiable change and wait for Palworld to confirm a save.
5. Request shutdown through the client.
6. Confirm PalServer exits before compression and the upload creates a higher version.
7. Confirm there is no `pending-session.json` and no active lock.

## Host B

1. Confirm it cannot start while Host A owns the lock.
2. After A finishes, run the normal connection/start flow.
3. Confirm B downloads A's version and verifies SHA-256 and `worldGuid`.
4. Start Palworld and verify A's change in-game.
5. Make a second identifiable change, then stop and publish from B.

## Recovery and rejection cases

- [ ] Simulate network loss after creating the local ZIP; the pending artifact must remain.
- [ ] Retry and confirm reconciliation without inventing a new `baseVersion`.
- [ ] Point deliberately at a different world and confirm publication is rejected.
- [ ] Restore an old version administratively in the isolated environment and confirm restore creates a new higher version.

## Evidence safe to publish

Record only versions, HTTP status codes, result and client/product version. Do not publish tokens, real paths, GUIDs, personal names, full logs or saves. Record commit, date and `PASS/FAIL` for the release candidate.
