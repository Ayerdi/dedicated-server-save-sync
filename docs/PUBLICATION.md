# Checklist para hacer público el repositorio

La publicación pública se hace desde un commit con CI verde. El repositorio no
debe contener saves, secretos ni datos del despliegue real.

## Estado del candidato v2.2.1

- [x] Apache-2.0.
- [x] README ES/EN, seguridad, soporte, contribución y conducta.
- [x] CI funcional: backend, E2E normal, E2E crash/restart, Windows/Pester y Gitleaks.
- [x] Dependencias Python bloqueadas por hash y `pip-audit`.
- [x] Gitleaks ejecutado con `fetch-depth: 0` sobre el historial Git.
- [x] Comprobador adicional contra `.env`, saves, ZIP, SQLite y claves.
- [x] Builder de cliente determinista y checksum SHA-256.
- [x] Supervisor de backup durable independiente de Gunicorn.
- [x] Restic 0.18.0 fijado por versión y SHA-256 para amd64/arm64.
- [x] Retención crash-safe: COMMIT de metadata antes de revalidar/eliminar ZIPs.
- [x] GitHub Pages ES/EN versionado en `site/` y bloqueado mientras el repo sea privado.
- [x] Fuente de Wiki ES/EN versionada en `wiki/`.
- [x] Scripts de publicación exigen checkout limpio, `main`, `HEAD == origin/main`
  y CI verde para el SHA exacto.
- [x] Release v2.2.1 calibrada en CI con doble build reproducible.
- [x] Release v2.2.1 publicada y verificada con target, assets y digest exactos.
- [x] Workflow one-shot de publicación retirado después de crear la release.
- [ ] Visibilidad GitHub cambiada de `private` a `public`.
- [ ] Configuración post-publicación aplicada con
  `scripts/configure-public-repository.sh --apply`.
- [ ] Wiki inicializada en GitHub y sincronizada con `scripts/publish-wiki.sh --apply`.

La release `v2.2.1` fue publicada desde:

```text
65b5d8c4b6c80b0560a712c87ddee5c4e76cbaec
```

Su ZIP publicado tiene exactamente este digest GitHub:

```text
sha256:4ee67ecdb617374c74f39db3819d6a6dae50618111102fa8a196c3f2beceacfc
```

Assets esperados y verificados:

```text
dedicated-server-save-sync-client-v2.2.1.zip
dedicated-server-save-sync-client-v2.2.1.zip.sha256
```

El script post-publicación resuelve el commit del tag `v2.2.1`, exige que la
release apunte a ese mismo commit y compara estado, lista de assets y digest
antes de modificar Settings. Si el tag/release o sus assets se sustituyesen,
aborta.

La prueba destructiva de [aceptación manual](../client/MANUAL-ACCEPTANCE.md) se
mantiene como procedimiento de regresión. El proyecto ya ha sido usado en el
flujo de hosts alternos y dispone de E2E aislado y pruebas de recuperación; no
se deben publicar GUIDs, rutas o nombres de esa instalación como evidencia.

## Antes del cambio de visibilidad

Usa un checkout limpio y actualizado:

```bash
git switch main
git pull --ff-only origin main
git fetch --tags
```

Comprueba que la release estable existe y que la CI del HEAD actual está verde.
`scripts/configure-public-repository.sh --apply` vuelve a comprobarlo; estas
comprobaciones manuales son una segunda barrera, no un sustituto del script.

## Único paso que exige intervención del propietario

El script deliberadamente **no cambia la visibilidad**. El propietario debe usar:

**Settings → General → Danger Zone → Change repository visibility → Public**

Después, sin introducir ningún cambio local:

```bash
bash scripts/configure-public-repository.sh --apply
```

El script aborta antes de tocar Settings si:

- el repositorio no es público;
- el checkout no está limpio;
- no se está en `main`;
- `HEAD` no coincide con `origin/main`;
- la CI más reciente de `main` no está verde para ese SHA exacto;
- el tag `v2.2.1` no existe o no es ancestro de `main`;
- la release `v2.2.1` no apunta al tag o no coincide con assets/digest auditados.

Cuando los preflight pasan:

- configura descripción, homepage, Issues, Discussions y Wiki;
- aplica topics;
- activa alertas de vulnerabilidades y Private Vulnerability Reporting;
- protege `main` con los cuatro jobs de CI y resolución obligatoria de conversaciones;
- habilita GitHub Pages con `build_type=workflow` y HTTPS;
- dispara Pages. El propio workflow vuelve a comprobar que el repo es público.

## Wiki

`scripts/publish-wiki.sh --apply` solo publica desde un checkout limpio y
sincronizado de `main` cuya CI esté verde. Por tanto, cambios locales en
`wiki/` nunca pueden saltarse PR/CI y acabar en la Wiki.

GitHub puede requerir crear una primera página antes de clonar una Wiki vacía.
Si el script indica que la Wiki todavía no está inicializada:

1. abre la pestaña **Wiki**;
2. crea una página `Home` mínima;
3. vuelve al checkout limpio de `main` y ejecuta:

   ```bash
   bash scripts/publish-wiki.sh --apply
   ```

La fuente autoritativa permanece en `wiki/`, dentro del repositorio principal.

## Verificación pública

Tras configurar el repositorio:

```bash
gh repo view Ayerdi/dedicated-server-save-sync \
  --json visibility,homepageUrl,hasIssuesEnabled,hasDiscussionsEnabled,hasWikiEnabled

gh release view v2.2.1
gh run list --workflow pages.yml --limit 1
```

Verificar además:

- release v2.2.1 y checksum descargables sin autenticación;
- digest del ZIP idéntico al fijado en este documento;
- web ES y EN servidas por HTTPS;
- `SECURITY.md` visible y Private Vulnerability Reporting habilitado;
- protección de `main` y checks obligatorios;
- Issues y Discussions;
- Wiki ES/EN sincronizada.

## Rollback

Si aparece información privada:

1. volver a `private` inmediatamente;
2. revocar cualquier secreto;
3. retirar releases/artefactos afectados;
4. limpiar el historial con una herramienta adecuada;
5. volver a ejecutar Gitleaks antes de considerar otra apertura.

Borrar un archivo en un commit posterior **no** elimina el dato de su historial.
