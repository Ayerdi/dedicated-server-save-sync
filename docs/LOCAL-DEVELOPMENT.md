# Desarrollo local aislado

Este modo sirve para validar backend, API y persistencia sin Traefik ni
Authentik. Publica el puerto únicamente en `127.0.0.1` y desactiva HTTPS dentro
del entorno local. Nunca debe reutilizarse como despliegue de Internet.

## Arranque manual

```bash
cp .env.local.example .env.local
chmod 600 .env.local
docker compose --env-file .env.local \
  -p save-sync-local \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  up --detach --build --wait
```

El token exclusivamente local del ejemplo es `local-development-token`. Para
evitar copiarlo accidentalmente a otra instalación, léelo del fichero local:

```bash
local_token="$(sed -n 's/^.*"token":"\([^"]*\)".*$/\1/p' .env.local)"
curl --fail-with-body \
  -H "Authorization: Bearer ${local_token}" \
  http://127.0.0.1:18080/api/games/palworld/status
```

Detener y eliminar también el volumen de prueba:

```bash
docker compose --env-file .env.local \
  -p save-sync-local \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  down --volumes --remove-orphans
```

## E2E automatizado

```bash
bash scripts/local-e2e.sh
```

La prueba crea un proyecto y volumen efímeros, y verifica:

```text
bootstrap → status v0 → lock → upload v1 → download/hash
→ descarga histórica → restore v2 → world_guid_conflict
→ lock conservado → unlock
```

El `trap` retira contenedor, red, volumen y temporales incluso si una aserción
falla. No accede al despliegue de producción ni ejecuta PalServer.

## Troubleshooting

- `port is already allocated`: cambia `SAVE_SYNC_LOCAL_PORT` en `.env.local`.
- `container name is already in use`: cambia `SAVE_SYNC_CONTAINER_NAME`.
- El healthcheck no pasa: revisa `docker compose ... logs` y confirma que los
  secretos de desarrollo tienen al menos 32 caracteres.
- Un token local no funciona: elimina el volumen y repite el bootstrap; no
  reutilices la variable bootstrap en producción.
