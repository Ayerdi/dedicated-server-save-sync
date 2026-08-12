# Dedicated Server Save Sync v2.2.0

`v2.2.0` closed the feature-development phase of Dedicated Server Save Sync as a stable Palworld reference implementation.

## Highlights

- Added `GET /backup-status` and an operational backup card in the private panel.
- Added conservative state handling for stale backup markers.
- Separated “the current version was backed up” from “automatic backups are enabled now”.
- Removed the 500-event limit when finding the latest successful backup.
- Made backup observability failures degrade safely without breaking the panel.
- Included configurable retention, post-publication external backup and auditing from the previous maintenance line.
- Prepared public documentation, GitHub Pages and versioned Wiki source.

## Verification

- 101 Python tests.
- 86.63% coverage.
- Clean Ruff run.
- `pip-audit` with no known vulnerabilities.
- Successful Docker build and isolated E2E.
- Successful Pester run on Windows.
- Gitleaks over Git history.

## Assets

```text
dedicated-server-save-sync-client-v2.2.0.zip
dedicated-server-save-sync-client-v2.2.0.zip.sha256
```

The client archive was built deterministically twice and compared before publication.

## Scope

From this release onward the repository entered maintenance mode: bugs, security, dependencies and Palworld compatibility. A broader multi-game redesign is developed separately.
