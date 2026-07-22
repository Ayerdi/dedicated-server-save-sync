# Seguridad

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

## Reporte

Al ser un repositorio privado, comunicar vulnerabilidades directamente a su
propietario. No abrir incidencias públicas con datos del despliegue.
