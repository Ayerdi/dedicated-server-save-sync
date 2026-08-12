# Contrato API

La base canónica contiene el juego configurado:

```text
https://sync.example.com/api/games/{gameKey}
```

Para el adaptador incluido:

```text
https://sync.example.com/api/games/palworld
```

Todas las llamadas del cliente envían
`Authorization: Bearer <token>` y `Accept: application/json`. El token no se
admite en URL. Los errores siempre tienen:

```json
{"error":"machine_code","message":"Descripción","details":{}}
```

## Identidad configurable

Cada `config/games/{gameKey}.json` declara `identityField`, `identityPattern` y
normalización. Todas las respuestas usan `saveIdentity` y también el nombre
específico del adaptador. Palworld devuelve por tanto ambos:

```json
{
  "saveIdentity": "A7E97BAA767DB9029EF013BB71E993A0",
  "worldGuid": "A7E97BAA767DB9029EF013BB71E993A0"
}
```

## Estado

```http
GET /status
```

Sin inicializar:

```json
{
  "gameKey": "palworld",
  "game": "Palworld",
  "identityField": "worldGuid",
  "initialized": false,
  "version": 0,
  "saveIdentity": null,
  "worldGuid": null,
  "sha256": null,
  "size": 0,
  "updatedAt": null,
  "updatedBy": null,
  "locked": false,
  "lock": null
}
```

Cuando está ocupado, `lock` contiene únicamente `owner`, `createdAt`,
`lastHeartbeatAt` y `expiresAt`; nunca contiene `sessionId`.

## Adquirir lock

```http
POST /lock
Content-Type: application/json
```

```json
{"owner":"Host A","clientId":"host-a-pc"}
```

`201 Created`:

```json
{
  "gameKey": "palworld",
  "sessionId": "valor-opaco",
  "baseVersion": 12,
  "saveIdentity": "A7E97BAA767DB9029EF013BB71E993A0",
  "worldGuid": "A7E97BAA767DB9029EF013BB71E993A0",
  "expiresAt": "2026-01-01T21:20:00Z"
}
```

Un lock activo devuelve `409 lock_occupied`. Solo el mismo usuario, token y
`sessionId` pueden renovarlo, usarlo o liberarlo.

## Heartbeat y unlock

```http
POST /heartbeat
POST /unlock
Content-Type: application/json
```

```json
{"sessionId":"valor-opaco"}
```

Heartbeat correcto:

```json
{"ok":true,"expiresAt":"2026-01-01T21:21:00Z"}
```

Sesión incorrecta o caducada: `409 invalid_session` o `409 lock_expired`.

## Descargar vigente

```http
GET /download
```

Cabeceras genéricas:

```http
X-Save-Sync-Version: 12
X-Save-Sync-SHA256: 0123456789abcdef...
X-Save-Sync-Identity: A7E97BAA767DB9029EF013BB71E993A0
Content-Disposition: attachment; filename="palworld-save-v12.zip"
```

El adaptador Palworld añade por compatibilidad `X-Palworld-Version`,
`X-Palworld-SHA256` y `X-Palworld-World-Guid`. Sin save devuelve
`404 save_not_initialized`.

## Publicar

```http
POST /upload
Content-Type: multipart/form-data
```

Campos comunes obligatorios:

```text
file
sessionId
baseVersion
sha256
```

También se exige el campo declarado por el adaptador. Palworld usa `worldGuid`;
el alias genérico `saveIdentity` también se acepta. `owner` es compatible pero
la identidad real procede del token.

`201 Created`:

```json
{
  "ok": true,
  "gameKey": "palworld",
  "previousVersion": 12,
  "version": 13,
  "saveIdentity": "A7E97BAA767DB9029EF013BB71E993A0",
  "worldGuid": "A7E97BAA767DB9029EF013BB71E993A0",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "size": 196105843,
  "updatedAt": "2026-01-01T22:03:00Z"
}
```

Conflicto de versión:

```json
{
  "error": "version_conflict",
  "message": "La versión remota ha cambiado.",
  "details": {"expectedBaseVersion":13,"receivedBaseVersion":12}
}
```

Conflicto de identidad:

```json
{
  "error": "world_guid_conflict",
  "message": "El ZIP pertenece a un mundo de Palworld diferente.",
  "details": {
    "identityField": "worldGuid",
    "expectedSaveIdentity":"A7E97BAA767DB9029EF013BB71E993A0",
    "receivedSaveIdentity":"B8F08CBB878ECA13AF1024CC82FAA4B1",
    "expectedWorldGuid":"A7E97BAA767DB9029EF013BB71E993A0",
    "receivedWorldGuid":"B8F08CBB878ECA13AF1024CC82FAA4B1"
  }
}
```

Los conflictos `409` no cambian ZIP, versión ni lock. Otros errores:

- `400 invalid_save_identity` o parámetros ausentes;
- `413 upload_too_large`;
- `422 sha256_mismatch` o ZIP inválido;
- `429 rate_limit_exceeded`;
- `503 storage_unavailable`.

Otros adaptadores usan `save_identity_conflict` con los campos genéricos
`expectedSaveIdentity` y `receivedSaveIdentity`.

## Historial

```http
GET /history
```

Devuelve `gameKey`, `identityField` y `versions`. Cada versión contiene
`version`, `saveIdentity`, el campo específico del adaptador, `updatedBy`,
`updatedAt`, `size`, `sha256`, `baseVersion` y `restoredFromVersion`.

Administración:

```text
GET    /history/{version}/download
POST   /history/{version}/restore
DELETE /history/{version}
POST   /admin/force-unlock
GET    /admin/tokens
POST   /admin/tokens
DELETE /admin/tokens/{id}
GET    /admin/audit?limit=100
```

### Estado del backup externo

```http
GET /backup-status
```

Devuelve el estado observable del backup para que clientes y panel puedan
responder si el supervisor confirmó correctamente el hook de la versión vigente:

```json
{
  "enabled": true,
  "state": "completed",
  "latestPublishedVersion": 13,
  "latestVersionBackedUp": true,
  "pending": false,
  "pendingVersions": [],
  "stalePending": false,
  "stalePendingVersions": [],
  "lastAttempt": {
    "version": 13,
    "completedAt": "2026-08-12T10:00:00Z",
    "success": true,
    "exitCode": 0,
    "timedOut": false,
    "reason": null
  },
  "lastCompleted": {
    "version": 13,
    "completedAt": "2026-08-12T10:00:00Z",
    "success": true,
    "exitCode": 0,
    "timedOut": false,
    "reason": null
  }
}
```

`state` puede ser `not_initialized`, `disabled`, `pending`, `completed`,
`failed` o `unknown`. `unknown` indica que el backup está habilitado pero no hay
resultado auditable para la versión vigente. También se usa cuando el único
marcador de esa versión está vencido (`started_at < ahora - (timeout + 60s)`).
En ese caso `stalePending` es `true`, el marcador aparece en
`stalePendingVersions` y no se cuenta como pendiente activo en la presentación.

Los registros de `pending_backups` son una **cola durable**. `stalePending` es
solo diagnóstico de antigüedad: ni este GET ni la retención purgan una fila por
ser vieja. Si el web o `backup-supervisor` se reinician antes de registrar un
resultado final, la fila y el ZIP protegido sobreviven y el supervisor vuelve a
reclamar el trabajo. Por diseño el hook puede ejecutarse más de una vez tras un
crash cuyo resultado quedó incierto.

`enabled` representa la configuración **actual** del hook y es independiente
del resultado histórico de la versión vigente. Por ejemplo, una versión que
se respaldó correctamente puede seguir devolviendo `state="completed"` y
`latestVersionBackedUp=true` después de desactivar el hook, mientras
`enabled=false` advierte que las publicaciones siguientes no encolarán backup
automático. Los clientes deben mostrar ambas dimensiones por separado.

`lastAttempt`, `lastCompleted` y el resultado de la versión vigente se obtienen
recorriendo la auditoría en orden descendente hasta encontrar los registros
válidos necesarios; no se pierden éxitos antiguos por un límite fijo de 500
eventos.

`latestVersionBackedUp=true` significa que el hook de la versión vigente
terminó con éxito y ese resultado quedó auditado por el supervisor. El endpoint
no consulta el repositorio restic ni verifica que el snapshot siga existiendo
en el momento de la consulta.

La llamada es solo lectura. Requiere autenticación, pero no rol administrador.

Restaurar crea una versión creciente y conserva `saveIdentity`.

## Ejemplos `curl`

Los ejemplos usan la ruta canónica. Las variables se definen en la shell, pero
el token nunca se incluye en la URL:

```bash
BASE=https://sync.example.com/api/games/palworld
TOKEN='pws_TOKEN_DEL_EQUIPO'
AUTH="Authorization: Bearer ${TOKEN}"
```

Estado, lock y heartbeat:

```bash
curl --fail-with-body -H "$AUTH" -H 'Accept: application/json' \
  "$BASE/status"

curl --fail-with-body -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  --data '{"owner":"Host A","clientId":"host-a-pc"}' \
  "$BASE/lock"

SESSION='SESSION_DEVUELTA_POR_LOCK'
curl --fail-with-body -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  --data "{\"sessionId\":\"${SESSION}\"}" \
  "$BASE/heartbeat"
```

Descarga, publicación y liberación sin publicar:

```bash
curl --fail-with-body -H "$AUTH" --output save.zip --dump-header headers.txt \
  "$BASE/download"

SHA256=$(sha256sum save.zip | cut -d' ' -f1)
curl --fail-with-body -X POST -H "$AUTH" \
  -F 'file=@save.zip;type=application/zip' \
  -F "sessionId=${SESSION}" \
  -F 'baseVersion=12' \
  -F "sha256=${SHA256}" \
  -F 'worldGuid=A7E97BAA767DB9029EF013BB71E993A0' \
  "$BASE/upload"

curl --fail-with-body -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  --data "{\"sessionId\":\"${SESSION}\"}" \
  "$BASE/unlock"
```

El adaptador de otro juego sustituye `worldGuid` por su `identityField`.
Historial y operaciones administrativas:

```bash
curl --fail-with-body -H "$AUTH" "$BASE/history"
curl --fail-with-body -H "$AUTH" --output historical.zip \
  "$BASE/history/7/download"
curl --fail-with-body -X POST -H "$AUTH" "$BASE/history/7/restore"
curl --fail-with-body -X DELETE -H "$AUTH" "$BASE/history/7"

curl --fail-with-body -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  --data '{"reason":"El equipo anfitrión fue verificado como apagado"}' \
  "$BASE/admin/force-unlock"

curl --fail-with-body -H "$AUTH" "$BASE/admin/tokens"
curl --fail-with-body -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  --data '{"username":"player","name":"host-b-pc"}' \
  "$BASE/admin/tokens"
curl --fail-with-body -X DELETE -H "$AUTH" "$BASE/admin/tokens/3"
curl --fail-with-body -H "$AUTH" "$BASE/admin/audit?limit=100"
```

Crear un token devuelve su valor plano una única vez. Los endpoints de
histórico, restauración, borrado, force-unlock, tokens y auditoría exigen rol
`admin`; el resto admite `admin` o `player`.

## Alias Palworld

`config/games/palworld.json` activa temporalmente estas rutas antiguas:

```text
/api/palworld/*
/palworld/api/*
/palworld
```

Los clientes y despliegues nuevos deben usar `/api/games/palworld` y
`/games/palworld`. Otros adaptadores no exponen los alias.

## Códigos HTTP

```text
200 operación correcta
201 recurso o versión creada
400 petición inválida
401 autenticación ausente o token inválido
403 permiso insuficiente o HTTPS requerido
404 recurso inexistente
409 lock, sesión, versión o identidad en conflicto
413 upload demasiado grande
422 hash o ZIP inválido
429 rate limit
500 error interno
503 almacenamiento no disponible
```
