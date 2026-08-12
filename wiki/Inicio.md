# Dedicated Server Save Sync

**Versión estable: v2.2.2 · Palworld**

Save Sync permite alternar qué PC aloja un servidor dedicado de Palworld sin copiar saves a mano ni mantener uno de los PCs encendido permanentemente.

## Empieza aquí

- [[Instalacion]]
- [[Cliente-Windows]]
- [[Backups-y-recuperacion]]
- [[Resolucion-de-problemas]]
- [[FAQ-Espanol]]
- [[Home|English]]

## Qué protege

Save Sync combina una versión autoritativa con `baseVersion`, un lock exclusivo con heartbeat, `worldGuid`, verificación SHA-256 y publicación atómica. Una copia antigua no puede sobrescribir silenciosamente progreso más reciente.

Los backups externos se encolan de forma durable en SQLite y los ejecuta un supervisor independiente del proceso web. Reiniciar el servicio web no pierde el trabajo pendiente.

Save Sync **no puede fusionar mundos que ya hayan divergido**. Si dos copias contienen progreso distinto, hay que decidir de forma explícita cuál será la autoritativa.

## Recursos

- [Repositorio](https://github.com/Ayerdi/dedicated-server-save-sync)
- [Web](https://ayerdi.github.io/dedicated-server-save-sync/)
- [Releases](https://github.com/Ayerdi/dedicated-server-save-sync/releases)
- [Seguridad](https://github.com/Ayerdi/dedicated-server-save-sync/security/policy)
