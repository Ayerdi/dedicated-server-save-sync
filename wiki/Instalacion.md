# Instalación

## Backend estable

Necesitas Docker Engine, Docker Compose v2, HTTPS y almacenamiento privado.
Usa el tag estable, no la punta cambiante de `main`:

```bash
git clone --branch v2.2.1 --depth 1 https://github.com/Ayerdi/dedicated-server-save-sync.git
cd dedicated-server-save-sync
config/deploy.sh --init-env
```

Revisa `.env` y ejecuta:

```bash
config/deploy.sh
```

El despliegue de v2.2.1 arranca tanto el backend como el `backup-supervisor` y
no publica la ruta hasta que ambos están healthy.

Para probarlo primero de forma aislada:

```bash
bash scripts/local-e2e.sh
```

## Cliente

Descarga `dedicated-server-save-sync-client-v2.2.1.zip` y su `.sha256` desde
**Releases**, verifica el checksum y continúa con [[Cliente-Windows]].

Cliente y backend deberían corresponder a la misma release estable.

Para producción lee también
[OPERATIONS.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/v2.2.1/docs/OPERATIONS.md).
