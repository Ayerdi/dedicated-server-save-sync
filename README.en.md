# Dedicated Server Save Sync

[Documentación completa en español](README.md)

Dedicated Server Save Sync coordinates one dedicated-game save between computers
that cannot remain online permanently. A continuously available web host stores
the authoritative ZIP, assigns monotonic versions and grants an exclusive,
expiring session lock before a computer starts the game server.

Palworld is the first production adapter. The backend is game-agnostic and each
additional game runs as an isolated instance with its own database, storage,
configuration and client adapter.

> Palworld is a trademark of Pocketpair, Inc. This community project is not
> affiliated with, sponsored by or endorsed by Pocketpair. It does not
> distribute game files or save content.

## Why this exists

Sharing ZIP files through cloud storage does not establish which copy is
authoritative. Two hosts can start divergent copies, file timestamps can change
during copying, and a valid ZIP may belong to a different world. This project
addresses those failure modes without claiming that divergent worlds can be
merged.

## Safety properties

- Server-assigned, monotonically increasing integer versions.
- Optimistic concurrency through `baseVersion`.
- Exclusive lock with a cryptographically random session ID, TTL and heartbeat.
- Adapter-defined save identity; Palworld uses a normalized 32-hex `worldGuid`.
- Server-side SHA-256 and defensive ZIP validation.
- Temporary upload followed by atomic publication and a database transaction.
- Per-computer Bearer tokens stored only as hashes by the backend.
- Admin-only restore, historical download, token management and force unlock.
- Retention by host slot, limiting the canonical ZIP count.

## Components

```text
save_sync/          Flask backend, SQLite schema and private panel
client/             Windows PowerShell 5.1 launcher
client/adapters/    Game-specific save/start/stop logic
config/             Docker, Traefik and deployment helpers
docs/               API, operations, migrations and adapter guidance
tests/              Concurrency, recovery, identity and security tests
```

Runtime stack: Python 3.11, Flask 3.1.3, Gunicorn, SQLite WAL, Docker
Compose, Traefik and optional Authentik protection for the web panel.

## Local verification

Docker is the only requirement for the isolated end-to-end check:

```bash
bash scripts/local-e2e.sh
```

It builds the pinned image and exercises bootstrap, lock, upload, download,
historical download, restore, world-identity conflict and unlock on localhost.
It does not start PalServer or access a production deployment.

For an interactive local environment:

```bash
cp .env.local.example .env.local
chmod 600 .env.local
docker compose --env-file .env.local \
  -p save-sync-local \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  up --detach --build --wait
```

Never expose this local override to the Internet: it deliberately disables the
HTTPS requirement and uses documented development-only credentials.

## Production models

- `SAVE_SYNC_PANEL_MODE=authentik`: API plus a private ForwardAuth-protected
  panel.
- `SAVE_SYNC_PANEL_MODE=disabled`: Bearer API only, with no panel route.

Production requires HTTPS, private filesystem storage and one isolated volume
per game. See [operations](docs/OPERATIONS.md) before deploying.

## Adding another game

An adapter must prove how to:

1. trigger and confirm a consistent save;
2. stop the process before archiving files;
3. identify a stable world, campaign or slot;
4. select the complete save unit and exclude transient files;
5. install a downloaded save with local rollback.

Add `config/games/<game-key>.json`,
`client/adapters/<game-key>/adapter.json`, the PowerShell adapter and its Pester
tests. Do not declare a game supported merely because its directory can be
compressed. See [adapter guidance](docs/ADAPTING-OTHER-GAMES.md).

## Development and security

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt
ruff check save_sync tests wsgi.py
python -m pytest -q
pip-audit -r requirements.txt --progress-spinner=off
```

The test suite enforces at least 85% Python coverage. CI also runs Docker E2E,
Pester on Windows and Gitleaks. Never commit real `.env`, client configuration,
tokens, saves, ZIP files, SQLite databases or rendered proxy routes.

Read [SECURITY.md](SECURITY.md) before reporting a vulnerability and
[CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes.

## Documentation

- [Documentation index](docs/INDEX.md)
- [Architecture and invariants](docs/ARCHITECTURE.md)
- [HTTP API](docs/API.md)
- [Operations](docs/OPERATIONS.md)
- [Local development](docs/LOCAL-DEVELOPMENT.md)
- [Migrations](docs/MIGRATIONS.md)
- [Release process](docs/RELEASES.md)
- [Public-release checklist](docs/PUBLICATION.md)
