# Installation

## Stable backend

You need Docker Engine, Docker Compose v2, HTTPS and private filesystem storage.
Use the stable tag rather than the moving tip of `main`:

```bash
git clone --branch v2.2.1 --depth 1 https://github.com/Ayerdi/dedicated-server-save-sync.git
cd dedicated-server-save-sync
config/deploy.sh --init-env
```

Review `.env`, then run:

```bash
config/deploy.sh
```

The v2.2.1 deployment starts both the backend and `backup-supervisor`, and does
not publish the route until both are healthy.

For an isolated validation first:

```bash
bash scripts/local-e2e.sh
```

## Client

Download `dedicated-server-save-sync-client-v2.2.1.zip` and its `.sha256` file
from **Releases**, verify the checksum, then continue with [[Windows-Client]].

Client and backend should come from the same stable release.

For production read
[OPERATIONS.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/v2.2.1/docs/OPERATIONS.md).
