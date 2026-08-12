# Dedicated Server Save Sync v2.2.1

`v2.2.1` completed the operational hardening before the repository became public. It did not change the client synchronization protocol, save/ZIP format or SQLite schema (v3).

## Durable backup independent from Gunicorn

- `pending_backups` became a durable SQLite queue.
- Publishing/restoring a version and enqueueing its backup became one SQLite commit.
- A separate `backup-supervisor` consumes the queue and runs the external hook.
- A Gunicorn crash does not stop the backup process.
- A supervisor crash leaves the row in SQLite for retry with **at-least-once** semantics.
- External commands must stay in the foreground and tolerate repetition.

## Crash safety and retention

Retention uses two phases: first commit audit/result/retention metadata, then reacquire a write lock, revalidate current references and only then unlink physical ZIPs that remain unreferenced.

The safe crash residue is an extra orphan ZIP, never committed SQLite metadata pointing at a ZIP deleted by a transaction that later rolled back.

Pending backup versions remain protected even when old. `stalePending` is observability, not permission to purge the queue.

## Supervisor and healthcheck

- Rejects unsupported `PRAGMA user_version` values.
- Requires a recent heartbeat and valid schema.
- Becomes unhealthy when work is queued but no backup command is configured.
- Runs hooks in their own process group and escalates `SIGTERM` to `SIGKILL` on timeout/shutdown.

## Reproducible restic

Restic 0.18.0 is downloaded from official assets and verified with pinned SHA-256 for amd64/arm64. CI checks the exact version inside the image.

## Validation

The hardening candidate was validated with Ruff, documentation checks, 132 Python tests with 88.38% coverage, `pip-audit`, Docker build/Compose, restic version verification, normal E2E, crash/restart E2E, Pester and full-history Gitleaks.

`clientVersion=1.2.0` remains the internal Palworld Windows component version and is independent from the product release number.
