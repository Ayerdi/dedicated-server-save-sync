# Dedicated Server Save Sync

**Versión estable: v2.2.2 · Palworld**

**Preview de desarrollo en `main`: Valheim 1.0 experimental + equipos gestionados**

Save Sync permite alternar qué PC aloja un servidor dedicado de Palworld sin copiar saves a mano ni mantener uno de los PCs encendido permanentemente.

## Empieza aquí

- [[Instalacion]]
- [[Cliente-Windows]]
- [[Backups-y-recuperacion]]
- [[Arquitectura]]
- [[Resolucion-de-problemas]]
- [[FAQ-Espanol]]
- [[Valheim-Experimental-Espanol]]
- [[Equipos-Gestionados]]
- [[Home|English]]

## Qué protege

Save Sync combina una versión autoritativa con `baseVersion`, un lock exclusivo con heartbeat, un `saveIdentity` definido por cada adaptador, verificación SHA-256 y publicación atómica. Palworld lo expone como `worldGuid`; Valheim experimental usa `worldUid`. Una copia antigua no puede sobrescribir silenciosamente progreso más reciente.

Los backups externos se encolan de forma durable en SQLite y los ejecuta un supervisor independiente del proceso web. Reiniciar el servicio web no pierde el trabajo pendiente.

Save Sync **no puede fusionar mundos que ya hayan divergido**. Si dos copias contienen progreso distinto, hay que decidir de forma explícita cuál será la autoritativa.

La release estable sigue siendo solo Palworld. La rama de desarrollo también incluye un adaptador aislado de Valheim; consulta [[Valheim-Experimental-Espanol]] para conocer su estado y requisitos de seguridad en vez de aplicar sin más las instrucciones de la release estable.

## Recursos

- [Repositorio](https://github.com/Ayerdi/dedicated-server-save-sync)
- [Web](https://ayerdi.github.io/dedicated-server-save-sync/)
- [Releases](https://github.com/Ayerdi/dedicated-server-save-sync/releases)
- [Seguridad](https://github.com/Ayerdi/dedicated-server-save-sync/security/policy)
