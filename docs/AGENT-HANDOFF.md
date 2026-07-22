# Handoff para un agente

Trabaja sobre este repositorio como un motor privado de sincronización de saves
para servidores dedicados. Palworld es el primer adaptador operativo; los demás
juegos deben mantener una instancia y un volumen independientes.

Lee, en este orden:

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/API.md`
4. `client/README.md`
5. `save_sync/app.py`
6. `client/SyncGame.ps1`
7. `client/adapters/palworld/Adapter.ps1`

## Invariantes que no deben romperse

- Las fechas de archivo nunca son autoridad de versión.
- Una subida requiere el `baseVersion` adquirido con el lock.
- `saveIdentity` no se inventa ni se sustituye para forzar una publicación.
- El proceso del juego debe estar cerrado antes de comprimir.
- El cliente no continúa jugando si pierde la exclusión de forma persistente.
- Los fallos conservan save, ZIP pendiente y versión vigente.
- Tokens, contraseñas, saves, bases de datos y configuraciones personales no se
  versionan ni se incluyen en logs.
- La REST local de Palworld no se expone a Internet.

## Forma de trabajar

1. Reproduce el problema con una prueba o evidencia concreta.
2. Explica cualquier cambio de comportamiento crítico y su riesgo.
3. Mantén compatibilidad con Windows PowerShell 5.1.
4. Ejecuta suite Python, Pester cuando haya Windows disponible, lint, build
   Docker y escaneo de secretos.
5. Documenta migración y rollback si cambia persistencia o despliegue.
6. No modifiques producción ni publiques artefactos sin autorización expresa.

## Entrega mínima

- archivos modificados y motivo;
- riesgos corregidos y pendientes;
- pruebas ejecutadas con resultado real;
- pasos de despliegue y rollback;
- cualquier desviación respecto al contrato.
