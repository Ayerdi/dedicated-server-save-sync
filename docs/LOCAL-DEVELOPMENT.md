# Isolated local development

This mode validates the backend, API and persistence without Traefik or Authentik. It binds only to `127.0.0.1` and disables HTTPS inside the local test environment. **Never expose this configuration to the Internet.**

## Manual startup

```bash
cp .env.local.example .env.local
chmod 600 .env.local
docker compose --env-file .env.local \
  -p save-sync-local \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  up --detach --build --wait
```

The example-only local token is `local-development-token`. Read it from the local file instead of copying it into commands elsewhere:

```bash
local_token="$(sed -n 's/^.*"token":"\([^"]*\)".*$/\1/p' .env.local)"
curl --fail-with-body \
  -H "Authorization: Bearer ${local_token}" \
  http://127.0.0.1:18080/api/games/palworld/status
```

Stop the stack and remove the test volume:

```bash
docker compose --env-file .env.local \
  -p save-sync-local \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  down --volumes --remove-orphans
```

## Automated E2E

```bash
bash scripts/local-e2e.sh
```

The test creates an isolated project and volume and checks:

```text
bootstrap → status v0 → lock → upload v1 → download/hash
→ historical download → restore v2 → identity conflict
→ lock preserved → unlock
```

Its cleanup trap removes containers, network, volume and temporary files even when an assertion fails. It never touches a production deployment or starts PalServer.

## Troubleshooting

- `port is already allocated`: change `SAVE_SYNC_LOCAL_PORT` in `.env.local`.
- `container name is already in use`: change `SAVE_SYNC_CONTAINER_NAME`.
- healthcheck fails: inspect `docker compose ... logs` and confirm development secrets are at least 32 characters.
- local token stops working: remove the test volume and bootstrap again; never reuse the development bootstrap token in production.
