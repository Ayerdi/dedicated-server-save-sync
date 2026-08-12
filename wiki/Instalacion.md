# Instalación

## Backend

Necesitas Docker Engine, Docker Compose v2, HTTPS y almacenamiento privado.

```bash
git clone https://github.com/Ayerdi/dedicated-server-save-sync.git
cd dedicated-server-save-sync
config/deploy.sh --init-env
```

Revisa `.env` y ejecuta:

```bash
config/deploy.sh
```

Para probarlo primero de forma aislada:

```bash
bash scripts/local-e2e.sh
```

## Cliente

Descarga el ZIP desde **Releases**, extrae el contenido y sigue
[[Cliente-Windows]].

Para producción lee también
[OPERATIONS.md](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/docs/OPERATIONS.md).
