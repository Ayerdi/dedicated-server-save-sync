# Adaptar el patrón a otros juegos

> **Referencia técnica, no soporte estable.** `v2.2.0` se publica y mantiene
> como implementación de referencia para Palworld. Este documento conserva el
> diseño genérico existente y los requisitos que una adaptación debería cumplir;
> no implica que este repositorio acepte nuevos juegos en su roadmap de
> mantenimiento. La futura plataforma multi-juego se desarrollará por separado.

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

La arquitectura actual aísla cada juego en su propia instancia y volumen. Esa
capacidad forma parte del diseño heredado, pero no convierte otros títulos en
integraciones soportadas.

## Investigación obligatoria

Antes de escribir un cliente para otro juego, responder con evidencia:

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

## Contrato mínimo de referencia

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

## Archivos que requeriría una adaptación

```text
config/games/<game-key>.json
client/adapters/<game-key>/adapter.json
client/adapters/<game-key>/Adapter.ps1
client/adapters/<game-key>/tests/*.Tests.ps1
```

Ejemplo de JSON backend:

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

Una instancia experimental debería usar `.env`, almacenamiento y proyecto
Compose independientes. No compartir base de datos ni directorio de saves entre
juegos.

## Adaptación del cliente

El lanzador común lee `Adapter` y `GameKey`, valida `adapter.json` y ejecuta el
`Adapter.ps1` correspondiente. Cualquier adaptación debe resolver de forma
segura:

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

## Checklist técnico de aceptación

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
