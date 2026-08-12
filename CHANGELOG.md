# Changelog

All notable changes to this project are documented here.

## Unreleased

No pending changes after v2.2.2.

## 2.2.2

- Makes English the canonical language for the repository, project website, contribution/support/security material, issue/PR templates and technical documentation.
- Keeps a complete Spanish localization in the versioned GitHub Wiki source while making the Wiki Home and FAQ English-first.
- Adds `Configure-Secrets.cmd`, `Test-Connection.cmd` and `Start-PalworldSync.cmd` as English aliases. Existing Spanish command filenames remain for backward compatibility.
- Aligns the public navigation and project structure with `Ayerdi/PROX2-AutoSwitch` without changing Save Sync's Palworld-specific architecture.
- Clarifies that the broader multi-game and future device/cloud-sync product belongs in a separate successor project.
- Refreshes stale documentation pointers and removes the old duplicated Spanish/English repository-home split.
- Does **not** change the synchronization API, save/ZIP format, SQLite schema, locking model, `worldGuid` handling or Palworld adapter protocol.

## 2.2.1

- Hardened public release and production deployment without changing the client protocol or save format.
- Required backend and client to come from the same stable product release.
- Converted `pending_backups` into a durable SQLite queue consumed by a `backup-supervisor` independent from Gunicorn.
- Made publication/restore and backup enqueue one SQLite commit.
- Preserved queue rows across web/supervisor crashes with at-least-once retry semantics.
- Changed retention to commit metadata before revalidating and deleting physical ZIPs.
- Kept stale pending backup rows protected; `stalePending` became an observability signal rather than an expiry rule.
- Pinned restic 0.18.0 by version and SHA-256 for amd64/arm64 and verified the resulting image in CI.
- Added Docker E2E coverage for web-worker and backup-supervisor crash/restart recovery.
- Required both backend and supervisor to become healthy before `config/deploy.sh` publishes the Traefik route.
- Expanded CI and publication preflights and documented the distinction between product release and `clientVersion=1.2.0`.

## 2.2.0

- Added `GET /backup-status` and an operational backup card in the panel.
- Separated the historical result for the current version from whether automatic backup is enabled now.
- Reported stale backup markers conservatively rather than as permanently active work.
- Removed the fixed 500-event window when finding the latest completed backup.
- Made `/backup-status` failures degrade safely without breaking the rest of the panel.
- Documented that `latestVersionBackedUp=true` is an audited hook result, not a live restic verification.
- Prepared the initial public README ES/EN, GitHub Pages, versioned Wiki source and deterministic v2.2.0 client package.
- Entered maintenance mode as the stable Palworld reference implementation.

## 2.1.1

- Updated dependencies and CI actions.
- Hardened external backup launch/error handling so a confirmed publication still returns success even when the optional hook cannot start.
- Inserted backup protection atomically during publish/restore.
- Protected in-progress backup versions from history deletion and retention.
- Added hook timeout and process-group termination.
- Introduced schema version 3 with `pending_backups`.
- Documented external backup consistency limits for live SQLite WAL storage.

## 2.1.0

- Added `SAVE_SYNC_RETENTION_PER_SLOT`.
- Added `SAVE_SYNC_POST_PUBLISH_COMMAND` for post-publication external backups.

## 2.0.0

- Adopted Apache License 2.0.
- Updated Flask and pinned transitive dependencies with hashes, `pip-audit` and coverage enforcement.
- Added isolated Docker E2E, API-only mode and configurable Traefik certificate resolver.
- Added explicit SQLite schema versioning and downgrade rejection.
- Generalized the backend around one `gameKey` per deployment and canonical `/api/games/{gameKey}` routes.
- Generalized Palworld `world_guid` into adapter-defined `save_identity` while keeping compatibility aliases.
- Split the Windows launcher from `client/adapters/palworld` and isolated deployment storage/database by game.

## 1.2.0

- Unified Windows clients into one configurable codebase.
- Added preferred selection of the authoritative remote world GUID.
- Added client version to the ZIP manifest and `LibraryOnly` testing mode.
- Parameterized domain, network, ForwardAuth, storage and identities.
- Replaced original deployment-specific data with neutral examples.

## 1.1.0

- Fixed local multi-world ambiguity when the remote authority already identifies the correct world.

## 1.0.0

- Initial operational implementation of backend, lock, versioning, `worldGuid`, Windows client and atomic publication.
