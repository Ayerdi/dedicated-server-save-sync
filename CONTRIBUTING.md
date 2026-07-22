# Contribuir

Gracias por ayudar a mejorar Dedicated Server Save Sync. Antes de proponer un
cambio, lee [SECURITY.md](SECURITY.md) y las invariantes de
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Antes de abrir una incidencia

- No adjuntes saves, ZIP, bases SQLite, tokens, contraseñas ni `.env` reales.
- Usa el formulario de seguridad privado para vulnerabilidades o información
  sensible.
- Para un juego nuevo, aporta evidencia de cómo guarda, cierra y distingue sus
  campañas; poder comprimir una carpeta no demuestra consistencia.

## Desarrollo

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt
ruff check save_sync tests wsgi.py
python -m pytest -q
pip-audit -r requirements.txt --progress-spinner=off
bash scripts/run-gitleaks.sh
bash scripts/local-e2e.sh
```

Las pruebas PowerShell requieren Windows PowerShell 5.1 y Pester 5.9.0:

```powershell
Import-Module Pester -RequiredVersion 5.9.0
Invoke-Pester -Path .\client -CI
```

## Pull requests

1. Crea una rama descriptiva.
2. Añade pruebas para cualquier cambio de comportamiento.
3. Mantén compatibilidad con Windows PowerShell 5.1 en el cliente.
4. Actualiza documentación, esquema y rollback cuando corresponda.
5. Ejecuta las comprobaciones anteriores.
6. Completa la plantilla de PR sin incluir datos del despliegue.

Los commits deben ser pequeños y usar mensajes convencionales, por ejemplo
`fix: reject stale upload` o `feat: add example-game adapter`.

## Dependencias

Edita `requirements.in` o `requirements-dev.in` y regenera los locks:

```bash
bash scripts/update-dependencies.sh
```

No edites manualmente los archivos compilados `requirements*.txt`.
