# Dedicated Server Save Sync v2.2.2

`v2.2.2` is a documentation/packaging maintenance release. It makes the public project consistently English-first while preserving a complete Spanish Wiki and backward-compatible Windows entrypoints.

## What changed

- English is now canonical for README, Pages, technical docs, maintenance docs, templates and release documentation.
- The GitHub Wiki source is fully bilingual: English Home/FAQ/navigation plus a complete Spanish path beginning at `Inicio`.
- The Windows package adds English entrypoints:
  - `Configure-Secrets.cmd`
  - `Test-Connection.cmd`
  - `Start-PalworldSync.cmd`
- Existing Spanish `.cmd` entrypoints remain in the package so old shortcuts and automation continue to work.
- Public navigation is aligned with the companion `Ayerdi/PROX2-AutoSwitch` project: README → Website → Wiki → Docs/Support/Security → Releases.
- Scope language now explicitly reserves the future multi-game and device/cloud-sync product for a separate successor repository.

## Compatibility

There are no intentional changes to:

- the synchronization HTTP API;
- `baseVersion` or lock semantics;
- `saveIdentity` / `worldGuid` rules;
- save or ZIP format;
- SQLite schema (still v3);
- Palworld REST interaction;
- `clientVersion=1.2.0`.

This is therefore a patch release rather than a feature/minor release.

## Release assets

The release publishes:

```text
dedicated-server-save-sync-client-v2.2.2.zip
dedicated-server-save-sync-client-v2.2.2.zip.sha256
```

The workflow builds the client twice, compares SHA-256 and ZIP bytes, then publishes only if both builds are identical.
