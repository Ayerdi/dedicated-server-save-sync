# Aceptación manual con Palworld

Esta prueba debe ejecutarse en dos equipos Windows de prueba antes de publicar
el primer release. Usa backups externos y una instancia Save Sync aislada; no
experimentes con el único save válido.

## Preparación

- [ ] Ambos equipos usan el mismo commit/artefacto del cliente.
- [ ] Cada equipo tiene token propio y `ClientId` distinto.
- [ ] La REST de Palworld escucha solo en localhost.
- [ ] Existe una copia externa verificada del mundo.
- [ ] Ningún `PalServer.exe` está abierto.

## Equipo A

1. Ejecutar `Configurar-secretos.cmd` y `Probar-conexion.cmd`.
2. Iniciar con `Iniciar-PalworldSync.cmd`.
3. Confirmar que adquiere lock y selecciona el `worldGuid` esperado.
4. Conectar un cliente del juego, realizar un cambio identificable y esperar a
   que el juego confirme el guardado.
5. Solicitar cierre desde el script.
6. Confirmar que PalServer termina antes de comprimir y que el upload crea una
   versión nueva.
7. Verificar que no queda `pending-session.json` ni lock activo.

## Equipo B

1. Confirmar que no puede iniciar mientras A mantiene el lock.
2. Tras cerrar A, ejecutar conexión e inicio normales.
3. Confirmar que descarga la versión de A y verifica SHA-256 y `worldGuid`.
4. Arrancar Palworld y comprobar dentro del juego el cambio creado por A.
5. Crear otro cambio, cerrar y publicar desde B.

## Recuperación y rechazo

- [ ] Simular una caída de red después de crear el ZIP: el pendiente se conserva.
- [ ] Repetir conexión y confirmar reconciliación sin inventar `baseVersion`.
- [ ] Configurar deliberadamente otra carpeta de mundo y comprobar que se
  rechaza antes de publicar.
- [ ] Restaurar administrativamente una versión en el entorno aislado y
  confirmar que reaparece como número superior.

## Evidencia que puede publicarse

Registrar únicamente versiones, códigos HTTP, resultado y versión del cliente.
No adjuntar tokens, rutas, GUID reales, nombres personales, logs completos ni
saves. Anotar commit, fecha y `PASS/FAIL` en el release candidate.
