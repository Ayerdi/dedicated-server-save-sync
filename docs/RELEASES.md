# Releases

## Release estable actual

La release estable de referencia es `v2.2.0`.

GitHub Actions crea el paquete de cliente desde el commit de publicación y
adjunta:

```text
dedicated-server-save-sync-client-v2.2.0.zip
dedicated-server-save-sync-client-v2.2.0.zip.sha256
```

GitHub añade además los archivos fuente automáticos del tag.

## Builder reproducible

Para construir localmente:

```bash
bash scripts/build-release.sh 2.2.0
```

El builder:

- ordena los archivos;
- fija timestamp ZIP a 1980-01-01;
- normaliza permisos;
- excluye tests, `config.json`, secretos y `client/data`;
- genera SHA-256.

Comprueba reproducibilidad:

```bash
bash scripts/build-release.sh 2.2.0
first="$(cut -d' ' -f1 dist/dedicated-server-save-sync-client-v2.2.0.zip.sha256)"
rm -f dist/dedicated-server-save-sync-client-v2.2.0.zip*
bash scripts/build-release.sh 2.2.0
second="$(cut -d' ' -f1 dist/dedicated-server-save-sync-client-v2.2.0.zip.sha256)"
test "$first" = "$second"
```

## Automatización v2.2.0

`.github/workflows/release-v2.2.0.yml` se activa únicamente cuando el propio
workflow entra en `main`. Antes de crear la release:

1. ejecuta `scripts/check-repository.sh`;
2. construye el ZIP dos veces;
3. compara ambos SHA-256;
4. publica `v2.2.0` apuntando al commit exacto del workflow;
5. adjunta ZIP y checksum;
6. usa `docs/RELEASE-NOTES-v2.2.0.md` como notas.

Si `v2.2.0` ya existe, el workflow termina sin modificarla.

El tag creado por GitHub no se presenta como firma GPG del mantenedor. La
integridad del cliente se publica mediante SHA-256, y la procedencia se apoya en
el commit de `main`, CI y el workflow versionado.

## Releases posteriores de mantenimiento

Para una futura `v2.2.x`:

1. actualizar `CHANGELOG.md`;
2. ejecutar CI completa;
3. construir dos veces el artefacto;
4. crear un tag/release desde un commit de `main`;
5. adjuntar ZIP + SHA-256;
6. documentar claramente si cambia el cliente Palworld.

No publicar saves, datos runtime, configuración real ni logs como assets.
