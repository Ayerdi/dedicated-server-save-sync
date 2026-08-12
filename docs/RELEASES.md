# Releases

## Release estable actual

La release estable de referencia es `v2.2.0`.

La publicación original de `v2.2.0` se generó automáticamente desde el commit
`b085453f4bdd39d7c336980b0a27ce79605aa7a2`. El workflow construyó dos veces el
mismo cliente, comparó SHA-256 y contenido binario y solo entonces adjuntó:

```text
dedicated-server-save-sync-client-v2.2.0.zip
dedicated-server-save-sync-client-v2.2.0.zip.sha256
```

El workflow de una sola versión que realizó esa publicación se conserva en el
historial Git y en el tag, pero se retira de `main` después de cumplir su función
para no dejar permanentemente un workflow específico con `contents: write`.

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

La release publicada de `v2.2.0` tiene como digest del ZIP:

```text
4d07ce1eb70f79471dca8d5f1ed9c4d7a37aaebbf53f5668d84be2058a781494
```

Comprueba un build local contra su propio checksum con:

```bash
sha256sum --check dist/dedicated-server-save-sync-client-v2.2.0.zip.sha256
```

## Releases posteriores de mantenimiento

Las futuras releases se publican explícitamente desde un checkout limpio de
`main`; no existe un workflow con permiso de escritura esperando a un evento de
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

El script se niega a publicar si:

- el árbol tiene cambios locales;
- no se ejecuta desde `main`;
- `HEAD` difiere de `origin/main`;
- la CI más reciente de `main` no es `completed:success` para ese SHA;
- faltan changelog o notas;
- ya existe el tag o la release.

Si los preflight pasan, ejecuta `scripts/check-repository.sh`, genera el ZIP dos
veces, compara SHA-256 y bytes y crea la release apuntando al commit exacto.

El tag/release creado por GitHub CLI no se presenta como firma GPG del
mantenedor. La integridad del cliente se publica mediante SHA-256, y la
procedencia se apoya en el commit de `main`, la CI, la revisión por PR y el
proceso versionado de construcción.

No publicar saves, datos runtime, configuración real ni logs como assets.
