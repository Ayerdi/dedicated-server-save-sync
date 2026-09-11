# Installation

## Backend

Requirements:

- Docker Engine;
- Docker Compose v2;
- HTTPS;
- private filesystem storage.

Use the stable tag rather than the moving tip of `main`:

```bash
git clone --branch v2.2.2 --depth 1 https://github.com/Ayerdi/dedicated-server-save-sync.git
cd dedicated-server-save-sync
config/deploy.sh --init-env
```

Review `.env`, then deploy:

```bash
config/deploy.sh
```

The deployment starts both the web backend and `backup-supervisor` and does not publish the Traefik route until both are healthy.

For a safe isolated validation first:

```bash
bash scripts/local-e2e.sh
```

## Windows client

Download `dedicated-server-save-sync-client-v2.2.2.zip` and its `.sha256` file from **Releases**, verify the checksum, then continue with [[Windows-Client]].

Use backend and client from the same product release.

### Experimental Valheim

Valheim is not part of the stable v2.2.2 release package. For development testing, use backend and client from the same tested `main` commit/artifact, deploy a separate `gameKey=valheim` database/storage and follow [[Valheim-Experimental]] plus [[Managed-Computers]]. Do not replace the stable clone/tag instructions above with `main` for a production Palworld world.

For production details read [OPERATIONS.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/v2.2.2/docs/OPERATIONS.md).

[[Instalacion|Leer en español]]
