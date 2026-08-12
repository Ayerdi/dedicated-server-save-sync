# Releases

## Release estable actual

La release estable de referencia es `v2.2.1`.

`v2.2.1` cierra el hardening operativo previo a la publicación pública: cola
durable de backups, supervisor independiente de Gunicorn, retención crash-safe,
Restic 0.18.0 fijado por SHA-256 y E2E de caída/reinicio.

El cliente publicado contiene:

```text
dedicated-server-save-sync-client-v2.2.1.zip
dedicated-server-save-sync-client-v2.2.1.zip.sha256
```

La release se construye dos veces de forma determinista antes de publicarse. El
SHA-256 exacto del ZIP se calibró en CI sobre el mismo contenido empaquetable y
queda fijado en el preflight público antes del merge de publicación:

```text
sha256:4ee67ecdb617374c74f39db3819d6a6dae50618111102fa8a196c3f2beceacfc
```

Tras publicar, este documento se actualiza únicamente si GitHub confirma el
mismo digest. La release nunca se sobrescribe para hacerla coincidir con `main`.

## Release anterior v2.2.0

La publicación original de `v2.2.0` se generó desde el commit
`b085453f4bdd39d7c336980b0a27ce79605aa7a2`. El workflow construyó dos veces el
mismo cliente, comparó SHA-256 y contenido binario y adjuntó:

```text
dedicated-server-save-sync-client-v2.2.0.zip
dedicated-server-save-sync-client-v2.2.0.zip.sha256
```

Su digest histórico es:

```text
sha256:4d07ce1eb70f79471dca8d5f1ed9c4d7a37aaebbf53f5668d84be2058a781494
```

Ese dato se conserva como procedencia histórica; `v2.2.0` ya no es la release
recomendada para nuevas instalaciones.

## Builder reproducible

Para construir v2.2.1 localmente:

```bash
bash scripts/build-release.sh 2.2.1
sha256sum --check dist/dedicated-server-save-sync-client-v2.2.1.zip.sha256
```

El builder:

- ordena los archivos;
- fija timestamp ZIP a 1980-01-01;
- normaliza permisos;
- excluye tests, `config.json`, secretos y `client/data`;
- incluye `CHANGELOG.md`, `LICENSE` y `SECURITY.md`;
- genera SHA-256.

## Proceso de mantenimiento

Las releases posteriores se publican desde un checkout limpio de `main`; no se
mantiene permanentemente un workflow con permiso de escritura esperando un
push.

Preparación de una versión `X.Y.Z`:

1. actualizar `CHANGELOG.md` con una sección `## X.Y.Z`;
2. crear `docs/RELEASE-NOTES-vX.Y.Z.md`;
3. mergear por PR y esperar CI verde en el **HEAD exacto de `main`**;
4. actualizar el checkout local hasta coincidir con `origin/main`;
5. ejecutar:

   ```bash
   bash scripts/publish-release.sh X.Y.Z --apply
   ```

El script se niega a publicar si el árbol está sucio, no se ejecuta desde
`main`, `HEAD` difiere de `origin/main`, la CI exacta no está verde, faltan
changelog/notas o ya existe el tag/release. Si los preflight pasan, ejecuta el
safety check, genera el ZIP dos veces, compara SHA-256 y bytes y crea la release
apuntando al commit exacto.

Para `v2.2.1`, al ser la release de apertura pública, se usa además un workflow
one-shot versionado: en PR solo calibra el build con `contents: read`; el job con
`contents: write` existe únicamente para el push de merge que crea la release.
El workflow se retira de `main` después de verificar la publicación.

No publicar saves, datos runtime, configuración real ni logs como assets.
