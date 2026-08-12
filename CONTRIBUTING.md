# Contribuir

Gracias por ayudar a mantener Dedicated Server Save Sync.

`v2.2.1` marca la implementación estable de referencia para Palworld. Este
repositorio acepta mantenimiento, no un rediseño de producto.

Antes de proponer un cambio, lee [SECURITY.md](SECURITY.md) y
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Alcance aceptado

Son apropiados:

- bugs y regresiones;
- seguridad;
- compatibilidad con nuevas versiones de Palworld;
- dependencias;
- tests;
- documentación;
- pequeñas mejoras operativas que preserven el modelo actual.

Quedan fuera del roadmap de este repositorio:

- instalación multi-juego en una sola instancia;
- discovery automático universal de saves;
- múltiples `ServerInstance` por backend;
- sustitución del cliente por un agente multiplataforma;
- cambios incompatibles de arquitectura para convertirlo en una plataforma.

La documentación de `docs/ADAPTING-OTHER-GAMES.md` se conserva como referencia
técnica del diseño genérico existente.

## Antes de abrir una incidencia

- No adjuntes saves, ZIP, bases SQLite, tokens, contraseñas ni `.env` reales.
- Usa el reporte privado de seguridad para vulnerabilidades o información
  sensible.
- Redacta GUIDs, dominios, rutas, IPs y nombres reales.

## Desarrollo

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt
bash -n scripts/*.sh config/*.sh
ruff check save_sync tests wsgi.py scripts/check-docs.py
python scripts/check-docs.py
python -m pytest -q
pip-audit -r requirements.txt --progress-spinner=off
docker compose config --quiet
bash scripts/run-gitleaks.sh
bash scripts/local-e2e.sh
```

Pruebas Windows:

```powershell
Import-Module Pester -RequiredVersion 5.9.0
Invoke-Pester -Path .\client -CI
```

## Pull requests

1. Crea una rama descriptiva.
2. Añade pruebas para cambios de comportamiento.
3. Mantén Windows PowerShell 5.1 en el cliente.
4. Actualiza documentación y rollback cuando corresponda.
5. Ejecuta las comprobaciones anteriores.
6. No incluyas datos del despliegue real.

Los commits deben ser pequeños y descriptivos, por ejemplo
`fix: reject stale upload`.

Toda contribución aceptada se licencia bajo [Apache-2.0](LICENSE), conforme a la
sección 5 de la licencia.

## Dependencias

Edita `requirements.in` o `requirements-dev.in` y regenera locks:

```bash
bash scripts/update-dependencies.sh
```

No edites manualmente `requirements*.txt`.
