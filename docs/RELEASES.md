# Releases

## Current stable release

The stable Palworld reference release is `v2.2.2`.

It is a documentation/packaging patch: English-first repository surfaces, fully bilingual Wiki source and English Windows command aliases while preserving the old entrypoint filenames. It does not change protocol, schema or save format.

Published assets:

```text
dedicated-server-save-sync-client-v2.2.2.zip
dedicated-server-save-sync-client-v2.2.2.zip.sha256
```

Release target:

```text
81b4592fff57fcc648402447419ff241fa316fcb
```

Client ZIP digest:

```text
sha256:7ed5df418fcefa26495adef1ce53b55390b2c0c3b6760543a945057668757774
```

See [RELEASE-NOTES-v2.2.2.md](RELEASE-NOTES-v2.2.2.md).

## Deterministic client builder

```bash
bash scripts/build-release.sh 2.2.2
sha256sum --check dist/dedicated-server-save-sync-client-v2.2.2.zip.sha256
```

The builder sorts files, pins ZIP timestamps to 1980-01-01, normalizes permissions, excludes tests/config/secrets/runtime data, includes license/security/changelog material and emits SHA-256.

## Maintenance release process

A future `X.Y.Z` release is published from a clean, synchronized `main` checkout after the exact commit is green in CI:

1. update `CHANGELOG.md`;
2. add `docs/RELEASE-NOTES-vX.Y.Z.md`;
3. merge through PR and wait for green CI;
4. build the client twice and compare bytes/checksum;
5. publish the tag/release against the exact commit.

The repository does not rewrite historical release assets to match newer `main`.

## Historical provenance

`v2.2.1` client digest:

```text
sha256:4ee67ecdb617374c74f39db3819d6a6dae50618111102fa8a196c3f2beceacfc
```

`v2.2.0` client digest:

```text
sha256:4d07ce1eb70f79471dca8d5f1ed9c4d7a37aaebbf53f5668d84be2058a781494
```
