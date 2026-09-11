# Adapting the pattern to other games

> **Technical reference, not stable support.** `v2.2.2` is published and maintained as the Palworld reference implementation. This document preserves the generic design decisions and requirements another adapter would need to satisfy. The future multi-game/device-sync product will be developed separately.

The development tree includes an experimental `valheim` adapter that exercises this contract against Valheim 1.0 folder-based world saves. It is intentionally isolated from the stable Palworld adapter and remains experimental until the real four-host acceptance checklist passes.

## Reusable primitives

The backend provides game-independent building blocks: tokens/roles, exclusive lock with TTL/heartbeat, monotonic versioning and `baseVersion`, hashing and atomic publication, history/restore/audit, observable backup state and adapter-defined `saveIdentity`.

Canonical routes live under `/api/games/{gameKey}`. Palworld keeps `worldGuid` and legacy route aliases only for compatibility with its adapter.

The current architecture isolates each game in its own deployment, database and volume. That isolation is useful, but it does **not** make other games officially supported.

## Research required before writing an adapter

Answer with evidence:

1. Which process owns or writes the save?
2. Is there a supported command/API for a clean save and shutdown?
3. When can the directory be copied without producing inconsistent state?
4. What stable identifier distinguishes campaigns, worlds or slots?
5. Can that identifier be read before and after startup?
6. Which files form one consistent save unit?
7. Which backups, temporary files, locks or caches must be excluded?
8. What save size and compression ratio are realistic?
9. How can a restore be validated in an isolated environment?

If the game has no native identity, a configured identity fixed on first upload is possible but weaker: the client must still prove that the selected local files represent that identity.

## Minimum reference contract

```text
status
lock
heartbeat
download
upload(baseVersion, saveIdentity, sha256)
unlock
history
restore
```

The backend must reject stale bases and conflicting identities with `409`. Restore must create a new increasing version.

## Files an adaptation would need

```text
config/games/<game-key>.json
client/adapters/<game-key>/adapter.json
client/adapters/<game-key>/Adapter.ps1
client/adapters/<game-key>/tests/*.Tests.ps1
```

An experimental instance must use independent `.env`, storage and Compose project names. Never share a database or save directory between games.

## Client responsibilities

An adapter must safely locate/validate the local save, confirm remote identity/version, save and shut down cleanly, create a manifest/archive, and install downloads with local rollback.

It must preserve these invariants:

- acquire the remote lock before touching the authoritative save;
- heartbeat for the whole session;
- stop the writer process before creating an archive;
- verify downloaded SHA-256;
- keep a pending ZIP when publication cannot be confirmed;
- do not release a modified session that was not published;
- never invent `baseVersion` or identity to force an upload.

## Acceptance checklist

- Two simultaneous lock attempts: only one wins.
- Two uploads based on the same version: only one publishes.
- Wrong identity: version, file and lock remain unchanged.
- Failure after temporary upload: the current version is still downloadable.
- Writer process still running: the client refuses to archive.
- Network failure: a clear local recovery artifact remains.
- Restore: creates a higher version.
- Private artifacts: cannot be fetched by public URL.
- Real save/shutdown/restore/start test passes for the adapted game.

A game is not compatible merely because its files can be zipped. Save consistency is the primary requirement.
