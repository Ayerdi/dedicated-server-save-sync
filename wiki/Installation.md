# Installation

## Backend

You need Docker Engine, Docker Compose v2, HTTPS and private filesystem storage.

```bash
git clone https://github.com/Ayerdi/dedicated-server-save-sync.git
cd dedicated-server-save-sync
cp .env.example .env
chmod 600 .env
config/deploy.sh --init-env
```

Review `.env`, then run:

```bash
config/deploy.sh
```

For an isolated validation first:

```bash
bash scripts/local-e2e.sh
```

## Client

Download the ZIP from **Releases**, extract it and continue with
[[Windows-Client]].

For production read
[OPERATIONS.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/docs/OPERATIONS.md).
