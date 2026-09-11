# Maintainer guide

This document is the shortest safe path into the current repository. `v2.2.2` remains the stable Palworld maintenance release. `main` additionally contains an experimental Valheim adapter, managed-host authorization and the modularized backend introduced after that release; the broader general multi-game/device-sync product is still outside this repository.

## Recommended reading order

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/API.md`
4. `client/README.md`
5. `save_sync/app.py`
6. `save_sync/sessions.py`
7. `save_sync/publications.py`
8. `save_sync/database.py`
9. `save_sync/backup_supervisor.py`
10. `client/SyncGame.ps1`
11. `client/adapters/palworld/Adapter.ps1`
12. `docs/VALHEIM.md` and `client/adapters/valheim/Adapter.ps1` when touching the experimental Valheim flow.

`docs/ADAPTING-OTHER-GAMES.md` is a design reference, not an active support roadmap.

## Invariants that must not regress

- File timestamps are never version authority.
- An upload must use the `baseVersion` acquired with the lock.
- `saveIdentity` is never invented or replaced to force publication.
- The game/server writer must be stopped before the save is archived.
- The client must not keep playing after persistent loss of remote exclusion.
- A managed-host session must revalidate the owning user, exact token, host binding and host state inside the write transaction before trusted lock/session/publication changes.
- A game process must not remain active into a lease-expiry window where another host could legitimately acquire the same authoritative save.
- Failures preserve the save, any pending ZIP and the current authoritative version.
- Pending backups stay in SQLite and protect their ZIP until a final known result.
- Retention commits metadata before physically deleting ZIPs that are revalidated as unreferenced.
- Tokens, passwords, saves, databases and personal configuration never enter source control or public logs.
- Palworld's local REST API is never exposed to the Internet.

## Working method

1. Reproduce the problem with a test or concrete evidence.
2. Explain any critical behavior change and its risk.
3. Keep Windows PowerShell 5.1 compatibility.
4. Run Python tests, Pester, lint, Docker build/E2E and secret scanning.
5. Document migration and rollback when persistence or deployment changes.
6. Use a PR and wait for green CI on the exact final SHA.
7. Never publish artifacts from a dirty checkout and never rewrite an existing release to match `main`.

## Maintenance scope

Appropriate: bugs/regressions, security, Palworld compatibility, focused fixes/hardening for the experimental Valheim adapter and managed-host capability, dependency/CI maintenance, documentation and small compatible operational improvements.

Out of scope: universal save discovery, one installation managing multiple games/instances, device/cloud sync as a new product mode, a new cross-platform agent, or incompatible changes intended to turn this reference into the future general platform.

## Minimum delivery for a meaningful change

- changed files and rationale;
- risks fixed and any remaining risks;
- tests actually executed and their result;
- deployment and rollback steps when relevant;
- any intentional deviation from the documented contract.
