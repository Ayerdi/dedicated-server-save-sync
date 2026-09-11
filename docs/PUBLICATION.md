# Public repository checklist

The repository is public. These controls must remain true after maintenance changes.

## Current state

- [x] Apache-2.0.
- [x] English canonical repository documentation.
- [x] Complete English + Spanish versioned Wiki source.
- [x] Backend, Docker E2E, Windows/Pester and full-history Gitleaks CI.
- [x] Hash-locked Python dependencies and `pip-audit`.
- [x] Deterministic client ZIP builder with SHA-256.
- [x] Durable backup supervisor independent from Gunicorn.
- [x] Restic 0.18.0 pinned for amd64/arm64.
- [x] Crash-safe retention.
- [x] GitHub Pages source under `site/`.
- [x] Issues, Discussions, Wiki and private vulnerability reporting enabled.
- [x] Protected `main` with required CI checks.
- [x] Stable Palworld release messaging remains distinct from experimental Valheim development-tree messaging.
- [x] Pages and versioned Wiki include the experimental Valheim/managed-host guidance without presenting it as a `v2.2.2` release feature.

## Release preflight

```bash
git switch main
git pull --ff-only origin main
git fetch --tags
bash scripts/check-repository.sh
bash scripts/run-gitleaks.sh
```

Confirm the exact final SHA is green before publishing.

## Wiki

The authoritative Wiki source lives under `wiki/`. English is the canonical landing flow; Spanish remains a complete localized flow beginning at `Inicio`. Development-tree features such as experimental Valheim must be updated in both languages before `scripts/publish-wiki.sh --apply` is run.

## Verify after maintenance

- latest stable release/checksum download publicly;
- Pages deploys successfully over HTTPS;
- Wiki English/Spanish navigation works;
- `SECURITY.md` points to private vulnerability reporting;
- `main` retains required checks;
- no real saves, secrets, GUIDs, domains, IPs, private paths or personal deployment data entered Git history.

## Emergency response to accidental exposure

If private information is discovered, restrict visibility if needed, revoke/rotate secrets, remove affected release assets, rewrite Git history when necessary and run a full-history secret scan before reopening. Deleting a file in a later commit does not remove it from history.
