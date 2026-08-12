# Dedicated Server Save Sync

**Versión estable: v2.2.1 · Palworld**

Save Sync permite alternar qué PC aloja un servidor dedicado de Palworld sin
copiar saves a mano ni mantener uno de los PCs encendido permanentemente.

## Empieza aquí

- [[Instalacion]]
- [[Cliente-Windows]]
- [[Backups-y-recuperacion]]
- [[Resolucion-de-problemas]]
- [[FAQ]]
- [[Home-English|English]]

## Qué protege

Save Sync usa una versión autoritativa, `baseVersion`, un lock con heartbeat,
`worldGuid`, SHA-256 y publicación atómica. Una copia antigua no puede
sobrescribir silenciosamente progreso más reciente.

Los backups externos se encolan de forma durable en SQLite y los ejecuta un
supervisor independiente del proceso web; un reinicio del host web no pierde la
supervisión del trabajo pendiente.

El proyecto no puede fusionar dos mundos que ya hayan divergido.

## Recursos

- [README](https://github.com/Ayerdi/dedicated-server-save-sync)
- [Web](https://ayerdi.github.io/dedicated-server-save-sync/)
- [Releases](https://github.com/Ayerdi/dedicated-server-save-sync/releases)
- [Seguridad](https://github.com/Ayerdi/dedicated-server-save-sync/security/policy)
