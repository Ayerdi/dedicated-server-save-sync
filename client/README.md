# Cliente Save Sync

`SyncGame.ps1` es el lanzador común para Windows PowerShell 5.1. Lee `Adapter` y
`GameKey`, comprueba el manifest y entrega el control a
`adapters/<adapter>/Adapter.ps1`. Toda diferencia por equipo vive en
`config.json` y en los secretos DPAPI.

## Instalación

1. Copiar esta carpeta a una ruta local estable.
2. Copiar `config.example.json` como `config.json`.
3. Ajustar `Adapter`, `GameKey`, `PlayerName`, `ClientId`, URL y rutas del juego.
4. Habilitar la REST API de Palworld solo en localhost y configurar su
   `AdminPassword`.
5. Ejecutar `Configurar-secretos.cmd`.
6. Ejecutar `Probar-conexion.cmd`.

No copiar `data/secrets.json` entre equipos. DPAPI lo liga al usuario y equipo
que lo creó.

## Configuración

- `PlayerName`: debe coincidir con el nombre mostrado configurado en el backend.
- `ClientId`: identificador estable y no secreto del equipo.
- `Adapter`: carpeta de integración, actualmente `palworld`.
- `GameKey`: debe coincidir con `adapter.json` y el backend desplegado.
- `ApiBaseUrl`: termina en `/api/games/<gameKey>` y debe usar HTTPS.
- `PalServerRoot` y `PalServerExecutable`: instalación dedicada.
- `SaveGamesRoot`: directorio padre de `0/<worldGuid>`.
- `GameUserSettingsPath`: archivo que contiene `DedicatedServerName`.
- `InitialWorldGuid`: solo para elegir el mundo de la primera subida; dejar vacío
  después de inicializar es válido.
- `RestApiBaseUrl`: debe apuntar a localhost.
- `HeartbeatSeconds`: debe ser claramente menor que el TTL del backend.
- `LocalBackupRetention`: ZIP locales conservados por el cliente.

Los campos restantes del ejemplo pertenecen al adaptador Palworld. Otro
adaptador debe documentar su propia configuración y no reutilizar campos sin
semántica equivalente.

## Uso de Palworld

Ejecutar `Iniciar-PalworldSync.cmd`. No abrir `PalServer.exe` por separado.

Durante una sesión, ENTER solicita guardar, apagar y publicar. Cerrar la ventana
o apagar el PC puede dejar una sesión pendiente; el lock remoto acabará
caducando, pero el progreso local requerirá revisión.

## Recuperación

Archivos bajo `data/`:

- `state.json`: versión local confirmada.
- `pending-session.json`: sesión modificada aún no confirmada.
- `pending-uploads/`: ZIP cuya publicación no pudo confirmarse.
- `backups/`: copias previas a descarga/sesión.
- `logs/`: diagnóstico sin tokens ni contraseñas deliberados.

Si existe una sesión pendiente:

1. no iniciar el otro equipo;
2. consultar la versión remota;
3. si avanzó, no subir automáticamente;
4. conservar el ZIP y decidir manualmente qué progreso debe prevalecer;
5. no editar `baseVersion`.

## Incidente corregido en 1.1

Cuando había varios mundos locales, el cliente original buscaba cualquier
candidato antes de descargar y abortaba por ambigüedad aunque el backend ya
indicara el GUID correcto. La versión común prefiere el GUID remoto cuando su
carpeta existe y no borra los otros mundos.

## Pruebas

El switch interno `-LibraryOnly` carga funciones sin ejecutar el flujo. Se usa
exclusivamente desde Pester:

```powershell
Invoke-Pester -Path .\client -CI
```

Debe complementarse con una prueba manual controlada en Windows/PalServer; la
CI no puede demostrar el comportamiento de la REST ni la consistencia real del
save del juego.
