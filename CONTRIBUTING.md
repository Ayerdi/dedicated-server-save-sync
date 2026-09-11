# Contributing

Thanks for helping maintain Dedicated Server Save Sync.

`v2.2.2` is the current stable Palworld reference release. `main` also contains an experimental Valheim adapter and managed-host backend capability that may receive focused bug fixes, tests, documentation and safety hardening. This repository still does not accept a broad product redesign: automatic discovery, multiple server instances, general device/cloud sync and a universal cross-platform agent belong in a separate project.

Before proposing a change, read [SECURITY.md](SECURITY.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Good contributions

- reproducible bug fixes and regression tests;
- security hardening;
- compatibility fixes for new Palworld versions;
- reproducible fixes and safety hardening for the experimental Valheim adapter;
- compatibility fixes that preserve the existing per-game capability model (`managedHosts`, `saveIdentity`, isolated deployments);
- dependency and CI maintenance;
- documentation improvements;
- small operational improvements that preserve the current model.

Out of scope here:

- one installation managing multiple games or server instances;
- universal save discovery;
- a new cross-platform agent;
- device/cloud synchronization as a new product mode;
- incompatible architecture changes whose goal is to turn this reference into the future general platform.

[docs/ADAPTING-OTHER-GAMES.md](docs/ADAPTING-OTHER-GAMES.md) remains a technical design reference, not an open-ended support roadmap. Valheim is the one experimental adapter currently implemented in this repository.

## Before opening an issue

Never attach real saves, ZIP archives, SQLite databases, tokens, passwords or `.env` files. Use private vulnerability reporting for sensitive security reports. Redact real GUIDs, domains, paths, IP addresses and personal names.

## Development checks

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt
bash -n scripts/*.sh config/*.sh
ruff check save_sync tests wsgi.py scripts/check-docs.py
python scripts/check-docs.py
python -m pytest -q
pip-audit -r requirements.txt --progress-spinner=off
docker compose config --quiet
bash scripts/run-gitleaks.sh
bash scripts/local-e2e.sh
```

Windows client tests:

```powershell
Import-Module Pester -RequiredVersion 5.9.0
Invoke-Pester -Path .\client -CI
```

## Pull requests

1. Work on a descriptive branch.
2. Add tests for behavior changes.
3. Keep the Windows client compatible with Windows PowerShell 5.1.
4. Document migration and rollback when persistence or deployment changes.
5. Run the relevant checks before opening the PR.
6. Never include data from a real deployment.

Keep commits focused and descriptive, for example `fix: reject stale upload`.

Accepted contributions are licensed under [Apache-2.0](LICENSE), consistent with section 5 of the license.

## Dependencies

Edit `requirements.in` or `requirements-dev.in`, then regenerate the locked files with:

```bash
bash scripts/update-dependencies.sh
```

Do not edit `requirements*.txt` by hand.
