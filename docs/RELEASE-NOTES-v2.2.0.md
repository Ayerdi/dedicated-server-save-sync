# v2.2.0 — Stable Palworld reference release

## Español

`v2.2.0` cierra la etapa funcional de Dedicated Server Save Sync como
implementación estable para Palworld.

### Novedades

- `GET /backup-status` y tarjeta de estado de backup en el panel.
- Estado conservador ante markers de backup vencidos.
- Separación visible entre “la versión actual fue respaldada” y “el backup
  automático está habilitado ahora”.
- Último backup correcto sin límite artificial de 500 eventos.
- Degradación segura: un fallo del endpoint de observabilidad no rompe el panel.
- Retención configurable, backup externo post-publicación y auditoría heredados
  de v2.1.1.
- Documentación pública ES/EN, GitHub Pages y fuente versionada para la wiki.

### Verificación del HEAD funcional

- 101 tests Python.
- 86,63 % de cobertura.
- Ruff limpio.
- `pip-audit` sin vulnerabilidades conocidas.
- Docker build y E2E correctos.
- Pester correcto en Windows.
- Gitleaks sobre el historial Git.

### Artefactos

La release adjunta:

- `dedicated-server-save-sync-client-v2.2.0.zip`
- `dedicated-server-save-sync-client-v2.2.0.zip.sha256`

El ZIP se construye de forma determinista. El workflow lo genera dos veces y
compara el SHA-256 antes de publicar.

### Alcance

Desde esta release el repositorio entra en mantenimiento: bugs, seguridad,
dependencias y compatibilidad Palworld. Un rediseño multi-juego de mayor alcance
se desarrollará por separado.

---

## English

`v2.2.0` closes the feature-development phase of Dedicated Server Save Sync as
a stable Palworld reference implementation.

### Highlights

- `GET /backup-status` and an operational backup card in the private panel.
- Conservative state handling for stale backup markers.
- Clear separation between “the current version was backed up” and “automatic
  backups are enabled now”.
- Latest successful backup is no longer limited by a 500-event window.
- Safe degradation: backup observability failures do not break the rest of the
  panel.
- Configurable retention, post-publication external backup and auditing from
  v2.1.1.
- Public Spanish/English documentation, GitHub Pages and versioned wiki source.

### Verified functional HEAD

- 101 Python tests.
- 86.63% coverage.
- Clean Ruff run.
- `pip-audit` with no known vulnerabilities.
- Successful Docker build and isolated E2E.
- Successful Pester run on Windows.
- Gitleaks over Git history.

### Assets

The release attaches:

- `dedicated-server-save-sync-client-v2.2.0.zip`
- `dedicated-server-save-sync-client-v2.2.0.zip.sha256`

The ZIP is deterministic. The workflow builds it twice and compares the SHA-256
before publication.

### Scope

From this release onward the repository is in maintenance mode: bugs, security,
dependency updates and Palworld compatibility. A broader multi-game redesign
will be developed separately.
