# Checklist para hacer público el repositorio

La publicación pública se hace desde un commit con CI verde. El repositorio no
debe contener saves, secretos ni datos del despliegue real.

## Estado del candidato v2.2.0

- [x] Apache-2.0.
- [x] README, seguridad, soporte, contribución y conducta.
- [x] CI funcional: backend, E2E, Windows/Pester y Gitleaks.
- [x] Dependencias Python bloqueadas por hash y `pip-audit`.
- [x] Gitleaks ejecutado con `fetch-depth: 0` sobre el historial Git.
- [x] Comprobador adicional contra `.env`, saves, ZIP, SQLite y claves.
- [x] Búsqueda manual de nombres, GUIDs y datos del despliegue antes de abrir.
- [x] Builder de cliente determinista y checksum SHA-256.
- [x] Release reproducible v2.2.0 automatizada desde GitHub Actions.
- [x] GitHub Pages ES/EN versionado en `site/`.
- [x] Fuente de wiki versionada en `wiki/`.
- [ ] Visibilidad GitHub cambiada de `private` a `public`.
- [ ] Configuración post-publicación aplicada con
  `scripts/configure-public-repository.sh --apply`.
- [ ] Wiki inicializada en GitHub y sincronizada con `scripts/publish-wiki.sh`.

La prueba destructiva de [aceptación manual](../client/MANUAL-ACCEPTANCE.md) se
mantiene como procedimiento de regresión. El proyecto ya ha sido usado de forma
real en el flujo de hosts alternos y dispone de E2E aislado y prueba de
recuperación/backup; no se deben publicar GUIDs, rutas o nombres de esa
instalación como evidencia.

## Último paso que exige intervención del propietario

GitHub no permite que la automatización del propio repositorio cambie de forma
segura su visibilidad. El propietario debe usar:

**Settings → General → Danger Zone → Change repository visibility → Public**

Inmediatamente después, desde un checkout limpio y autenticado con `gh`:

```bash
bash scripts/configure-public-repository.sh --apply
```

Ese script:

- confirma que el repositorio ya es público;
- configura descripción, homepage, Issues, Discussions y Wiki;
- aplica topics;
- activa alertas de vulnerabilidades y reporte privado;
- configura protección de `main`;
- habilita GitHub Pages con `build_type=workflow`;
- dispara el workflow de Pages.

El script **nunca cambia la visibilidad**.

## Wiki

GitHub requiere crear una primera página antes de clonar una wiki vacía. Si
`scripts/publish-wiki.sh --apply` indica que la wiki todavía no está
inicializada:

1. abre la pestaña **Wiki**;
2. crea una página `Home` mínima;
3. ejecuta de nuevo:

```bash
bash scripts/publish-wiki.sh --apply
```

La fuente autoritativa de la wiki permanece en `wiki/`, dentro del repositorio
principal, para que los cambios sigan pasando por PR y revisión.

## Verificación pública

Después del cambio de visibilidad:

```bash
gh repo view Ayerdi/dedicated-server-save-sync \
  --json visibility,homepageUrl,hasIssuesEnabled,hasDiscussionsEnabled,hasWikiEnabled

gh release view v2.2.0
gh workflow run pages.yml --ref main
```

Verificar además:

- release y checksum descargables sin autenticación;
- web ES y EN;
- `SECURITY.md` visible;
- reporte privado de vulnerabilidades habilitado;
- protección de `main`;
- Issues y Discussions;
- wiki.

## Rollback

Si aparece información privada:

1. volver a `private` inmediatamente;
2. revocar cualquier secreto;
3. retirar releases/artefactos afectados;
4. limpiar el historial con una herramienta adecuada;
5. volver a ejecutar Gitleaks antes de considerar otra apertura.

Borrar un archivo en un commit posterior **no** elimina el dato de su historial.
