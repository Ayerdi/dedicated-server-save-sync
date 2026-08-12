# Seguridad

## Versiones soportadas

| Versión | Soporte de seguridad |
|---|---|
| `2.x` | Sí, únicamente el último release |
| `< 2.0` | No |

## Reportar una vulnerabilidad

No abras una incidencia pública. Utiliza el formulario **Report a
vulnerability** de GitHub Security Advisories:

<https://github.com/Ayerdi/dedicated-server-save-sync/security/advisories/new>

Incluye versión, impacto, pasos mínimos y mitigaciones conocidas, pero no
adjuntes saves, tokens ni configuraciones reales. Los mantenedores confirmarán
la recepción y coordinarán la divulgación cuando exista una corrección.

Private Vulnerability Reporting se habilita **inmediatamente después** de
cambiar el repositorio a público mediante
`scripts/configure-public-repository.sh --apply`. Hasta completar ese paso no
uses una incidencia pública para información sensible.

## Datos que nunca deben versionarse

- `.env` real;
- tokens `pws_...`;
- contraseñas REST o exportaciones DPAPI;
- `config.json` de un equipo;
- saves, ZIP, SQLite y sidecars WAL/SHM;
- rutas runtime renderizadas de Traefik;
- logs, dumps o capturas del panel con tokens;
- dominios, usuarios, GUID o rutas privadas de un despliegue real.

La `.gitignore` cubre los nombres habituales, pero no reemplaza una revisión del
diff y un escaneo de secretos.

## Modelo de amenazas

- Un token robado permite operar como ese usuario hasta revocarlo.
- Un usuario autorizado malicioso puede declarar un GUID correcto para un ZIP
  incorrecto; el backend no interpreta `Level.sav`.
- DPAPI protege secretos en reposo, no frente a malware bajo el mismo usuario.
- El proxy debe eliminar cabeceras Authentik aportadas desde Internet.
- SQLite y ZIP dependen de permisos correctos del host.

## Antes de cada publicación

```bash
bash scripts/check-repository.sh
git diff --cached
```

La CI añade Gitleaks. Si se detecta un secreto real, no basta con borrarlo en un
commit posterior: revocarlo, rotarlo y limpiar el historial antes de publicar.

También se ejecutan `pip-audit`, cobertura, un E2E local aislado y Pester en
Windows. Ninguna prueba automatizada sustituye el backup externo ni una prueba
real del adaptador con el servidor del juego cerrado limpiamente.
