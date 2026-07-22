# Migraciones de esquema

SQLite registra la versión mediante `PRAGMA user_version`. Esta release usa el
esquema `2` y aplica DDL idempotente bajo `flock` y `BEGIN IMMEDIATE` durante el
arranque.

## Reglas

- Un esquema `0` compatible se normaliza a `2` después de validar columnas y
  triggers.
- Ejecutar el arranque varias veces conserva `user_version=2`.
- Una base con versión superior se rechaza: la aplicación nunca intenta un
  downgrade implícito.
- Una base Palworld Sync v1 con columna `world_guid` se rechaza y debe conservar
  su volumen separado.
- Las migraciones futuras deben ser incrementales, transaccionales y disponer
  de prueba desde cada versión soportada.

## Antes de actualizar

1. Impedir nuevas sesiones y confirmar que no existe lock activo.
2. Crear backup coherente con la SQLite Backup API, no copiando el fichero WAL
   en ejecución.
3. Guardar también los ZIP referenciados por `versions`.
4. Probar restauración del backup en otra ruta.
5. Desplegar y comprobar `PRAGMA integrity_check` y `PRAGMA user_version`.

Consulta el comando de backup en [OPERATIONS.md](OPERATIONS.md).

## Rollback

El rollback de imagen solo es seguro si la versión anterior admite el esquema
actual. Si no lo admite, detener el servicio y restaurar juntos el snapshot
SQLite y sus ZIP correspondientes. Nunca reutilizar sidecars `-wal` o `-shm`
de otra ejecución.
