# Adaptar el patrón a otros juegos

## Qué puede reutilizarse

El backend aporta primitivas independientes del juego:

- tokens y roles;
- lock exclusivo con TTL;
- contador de versión y `baseVersion`;
- almacenamiento temporal, hash y publicación atómica;
- historial, restauración y auditoría;
- panel de estado.

Las rutas HTTP canónicas son `/api/games/{gameKey}` y el contrato común usa
`saveIdentity`. Palworld conserva `worldGuid` y rutas antiguas únicamente como
compatibilidad de su adaptador.

Cada juego se despliega como instancia aislada. No hace falta duplicar el
backend, pero sí proporcionar un JSON, un adaptador de cliente y configuración
de almacenamiento/Compose propios.

## Investigación obligatoria

Antes de escribir el cliente de otro juego, responder con evidencia:

1. ¿Qué proceso posee o escribe el save?
2. ¿Existe comando/API para guardar y apagar limpiamente?
3. ¿Cuándo puede copiarse el directorio sin producir un estado inconsistente?
4. ¿Qué identificador estable distingue campañas, mundos o ranuras?
5. ¿Ese identificador puede obtenerse antes y después de arrancar?
6. ¿Qué archivos forman una unidad consistente?
7. ¿Hay backups internos, temporales, locks o cachés que deban excluirse?
8. ¿Qué tamaño y ratio de compresión son razonables?
9. ¿Cómo se valida una restauración en un entorno aislado?

Si no existe identificador nativo, puede usarse uno de configuración fijado en
la primera subida, pero ofrece menos protección: el cliente debe demostrar que
la carpeta elegida corresponde a esa identidad.

## Contrato mínimo recomendado

Mantener estas operaciones aunque cambien los nombres:

```text
status
lock
heartbeat
download
upload(baseVersion, saveIdentity, sha256)
unlock
history
restore
```

El backend debe rechazar con `409` tanto una base antigua como otra identidad.
Una restauración debe crear una versión nueva.

## Archivos nuevos para otro juego

```text
config/games/<game-key>.json
client/adapters/<game-key>/adapter.json
client/adapters/<game-key>/Adapter.ps1
client/adapters/<game-key>/tests/*.Tests.ps1
```

El JSON backend debe declarar:

```json
{
  "key": "example-game",
  "displayName": "Example Game",
  "identityField": "campaignId",
  "identityLabel": "Campaign ID",
  "identityPattern": "^[a-z0-9-]{3,64}$",
  "identityNormalization": "lowercase",
  "legacyPalworldRoutes": false
}
```

Después se crea un `.env` independiente con `SAVE_SYNC_GAME_KEY`, otro
`SAVE_SYNC_HOST_STORAGE_PATH` y, preferiblemente, otro
`SAVE_SYNC_COMPOSE_PROJECT`. `deploy.sh` genera nombres de ruta, contenedor y
alias de red aislados por juego.

## Adaptación del cliente

El lanzador común lee `Adapter` y `GameKey`, valida `adapter.json` y ejecuta el
`Adapter.ps1` correspondiente. El nuevo adaptador debe implementar o reutilizar
de forma segura estas responsabilidades:

- localizar y validar la partida local;
- confirmar identidad y versión del servidor;
- guardar y cerrar limpiamente;
- seleccionar archivos y crear manifest;
- instalar una descarga con rollback local.

Preservar:

- adquisición del lock antes de tocar el save;
- heartbeat durante toda la sesión;
- cierre del proceso antes de comprimir;
- verificación SHA-256 de descargas;
- ZIP pendiente si la publicación no puede confirmarse;
- no liberar el lock tras una sesión modificada que no se publicó;
- prohibición de inventar `baseVersion` o identidad para forzar un upload.

## Checklist de aceptación

- Dos adquisiciones simultáneas: solo una obtiene lock.
- Dos uploads sobre la misma base: solo uno publica.
- Identidad incorrecta: no cambia versión, archivo ni lock.
- Fallo después del temporal: la versión vigente sigue descargable.
- Proceso abierto: el cliente se niega a comprimir.
- Caída de red: se conserva una recuperación local inequívoca.
- Restauración: produce versión creciente.
- Artefactos privados: inaccesibles por URL.
- Prueba real de guardar, apagar, restaurar y arrancar el juego adaptado.

No declarar compatible un juego únicamente porque sus archivos puedan
comprimirse. La consistencia del guardado es el requisito principal.
