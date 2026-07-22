# Releases

## Preparación

1. Confirmar árbol limpio y CI verde.
2. Actualizar `CHANGELOG.md` y versión del adaptador cuando corresponda.
3. Ejecutar `bash scripts/build-release.sh 2.0.0`.
4. Ejecutar dos veces y comprobar que el SHA-256 no cambia.
5. Inspeccionar el ZIP: no debe contener `config.json`, `data/`, logs ni saves.

El builder usa orden, timestamps y permisos deterministas. Produce:

```text
dist/dedicated-server-save-sync-client-v2.0.0.zip
dist/dedicated-server-save-sync-client-v2.0.0.zip.sha256
```

## Publicación

```bash
git tag -s v2.0.0 -m 'release: v2.0.0'
git push origin v2.0.0
gh release create v2.0.0 \
  dist/dedicated-server-save-sync-client-v2.0.0.zip \
  dist/dedicated-server-save-sync-client-v2.0.0.zip.sha256 \
  --verify-tag --generate-notes
```

Si no existe una clave de firma configurada, no sustituir silenciosamente el
tag firmado por uno ligero: documentar la limitación y decidir explícitamente
el mecanismo de firma.

Los artefactos contienen solo el cliente parametrizable y documentación legal;
el backend se construye desde el commit etiquetado con dependencias bloqueadas.
