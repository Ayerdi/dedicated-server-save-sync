# Instalación

## Backend

Necesitas Docker Engine, Docker Compose v2, HTTPS y almacenamiento privado.

Usa el tag estable, no la punta cambiante de `main`:

```bash
git clone --branch v2.2.2 --depth 1 https://github.com/Ayerdi/dedicated-server-save-sync.git
cd dedicated-server-save-sync
config/deploy.sh --init-env
```

Revisa `.env` y despliega:

```bash
config/deploy.sh
```

El despliegue arranca tanto el backend web como `backup-supervisor` y no publica la ruta de Traefik hasta que ambos están healthy.

Para validarlo primero de forma aislada:

```bash
bash scripts/local-e2e.sh
```

## Cliente Windows

Descarga `dedicated-server-save-sync-client-v2.2.2.zip` y su `.sha256` desde **Releases**, verifica el checksum y continúa con [[Cliente-Windows]].

Backend y cliente deben proceder de la misma release del producto.

Para producción consulta [OPERATIONS.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/v2.2.2/docs/OPERATIONS.md).

[[Installation|Read in English]]
