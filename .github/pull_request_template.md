## Qué cambia

<!-- Describe el cambio y el problema que resuelve. -->

## Riesgo e invariantes

- [ ] No permite uploads sin `baseVersion` válido.
- [ ] No debilita lock, identidad, autenticación ni publicación atómica.
- [ ] No incluye secretos, saves ni configuración real.
- [ ] Incluye migración y rollback si cambia persistencia o despliegue.

## Verificación

- [ ] `ruff check save_sync tests wsgi.py`
- [ ] `python -m pytest -q`
- [ ] `pip-audit -r requirements.txt --progress-spinner=off`
- [ ] `bash scripts/local-e2e.sh`
- [ ] Pester, si cambia `client/`

## Documentación

<!-- Indica los documentos actualizados o explica por qué no aplica. -->
