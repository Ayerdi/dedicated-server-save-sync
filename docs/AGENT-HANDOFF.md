# Guía de mantenimiento para agentes y contribuidores

Este documento resume el contexto mínimo para trabajar en la referencia estable
de Palworld sin romper sus invariantes. `v2.2.1` está en mantenimiento; el
rediseño multi-juego de producto se desarrolla fuera de este repositorio.

## Orden de lectura

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/API.md`
4. `client/README.md`
5. `save_sync/app.py`
6. `save_sync/backup_supervisor.py`
7. `client/SyncGame.ps1`
8. `client/adapters/palworld/Adapter.ps1`

`docs/ADAPTING-OTHER-GAMES.md` se conserva como referencia del diseño genérico,
no como roadmap activo de soporte.

## Invariantes que no deben romperse

- Las fechas de archivo nunca son autoridad de versión.
- Una subida requiere el `baseVersion` adquirido con el lock.
- `saveIdentity` no se inventa ni se sustituye para forzar una publicación.
- El proceso del juego debe estar cerrado antes de comprimir.
- El cliente no continúa jugando si pierde la exclusión de forma persistente.
- Los fallos conservan save, ZIP pendiente y versión vigente.
- Los backups pendientes permanecen en SQLite y protegen su ZIP hasta un resultado final.
- La retención confirma metadata antes de eliminar físicamente ZIPs revalidados como huérfanos.
- Tokens, contraseñas, saves, bases de datos y configuraciones personales no se
  versionan ni se incluyen en logs.
- La REST local de Palworld no se expone a Internet.

## Forma de trabajar

1. Reproduce el problema con una prueba o evidencia concreta.
2. Explica cualquier cambio de comportamiento crítico y su riesgo.
3. Mantén compatibilidad con Windows PowerShell 5.1.
4. Ejecuta suite Python, Pester, lint, build Docker, E2E y escaneo de secretos.
5. Documenta migración y rollback si cambia persistencia o despliegue.
6. Publica cambios por PR y espera CI verde para el SHA exacto.
7. No publiques artefactos desde un árbol local sucio ni modifiques una release
   existente para hacerla coincidir con `main`.

## Alcance de mantenimiento

Apropiado:

- bugs y regresiones;
- seguridad;
- compatibilidad con versiones nuevas de Palworld;
- dependencias y CI;
- documentación;
- pequeñas mejoras operativas compatibles con la arquitectura actual.

Fuera de alcance:

- discovery universal de saves;
- una única instalación con múltiples juegos/instancias;
- un nuevo agente multiplataforma;
- cambios incompatibles cuyo objetivo sea convertir esta referencia en la
  futura plataforma generalista.

## Entrega mínima

- archivos modificados y motivo;
- riesgos corregidos y pendientes;
- pruebas ejecutadas con resultado real;
- pasos de despliegue y rollback cuando apliquen;
- cualquier desviación respecto al contrato.
