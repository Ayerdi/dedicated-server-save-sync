# HTTP API

The canonical base path includes the configured game:

```text
https://sync.example.com/api/games/{gameKey}
```

For the included Palworld adapter:

```text
https://sync.example.com/api/games/palworld
```

Client requests send:

```http
Authorization: Bearer <token>
Accept: application/json
```

Tokens are never accepted in the URL.

Errors use a stable machine-readable shape:

```json
{"error":"machine_code","message":"Human-readable explanation","details":{}}
```

## Save identity

Each `config/games/{gameKey}.json` declares `identityField`, `identityPattern` and normalization. API responses always expose the generic `saveIdentity`; an adapter may expose its specific field too.

Palworld example:

```json
{
  "saveIdentity": "A7E97BAA767DB9029EF013BB71E993A0",
  "worldGuid": "A7E97BAA767DB9029EF013BB71E993A0"
}
```

## Status

```http
GET /status
```

Uninitialized response:

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

When locked, `lock` contains only `owner`, `createdAt`, `lastHeartbeatAt` and `expiresAt`. It never contains `sessionId`.

## Acquire a lock

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
  "sessionId": "opaque-value",
  "baseVersion": 12,
  "saveIdentity": "A7E97BAA767DB9029EF013BB71E993A0",
  "worldGuid": "A7E97BAA767DB9029EF013BB71E993A0",
  "expiresAt": "2026-01-01T21:20:00Z"
}
```

An existing valid lock returns `409 lock_occupied`. Only the same authenticated user/token and matching `sessionId` may heartbeat, use or release it.

## Heartbeat and unlock

```http
POST /heartbeat
POST /unlock
Content-Type: application/json
```

```json
{"sessionId":"opaque-value"}
```

Successful heartbeat:

```json
{"ok":true,"expiresAt":"2026-01-01T21:21:00Z"}
```

Invalid or expired sessions return `409 invalid_session` or `409 lock_expired`.

## Download the authoritative version

```http
GET /download
```

Generic response headers:

```http
X-Save-Sync-Version: 12
X-Save-Sync-SHA256: 0123456789abcdef...
X-Save-Sync-Identity: A7E97BAA767DB9029EF013BB71E993A0
Content-Disposition: attachment; filename="palworld-save-v12.zip"
```

The Palworld adapter also exposes compatibility headers `X-Palworld-Version`, `X-Palworld-SHA256` and `X-Palworld-World-Guid`.

An uninitialized save returns `404 save_not_initialized`.

## Publish a version

```http
POST /upload
Content-Type: multipart/form-data
```

Required common fields:

```text
file
sessionId
baseVersion
sha256
```

The adapter identity field is also required. Palworld uses `worldGuid`; the generic alias `saveIdentity` is accepted too.

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

A stale base returns `409 version_conflict`. A different save identity returns an adapter-specific identity conflict (Palworld: `world_guid_conflict`) without changing the current file, version or lock.

Other important failures:

- `400 invalid_save_identity` or missing parameters;
- `413 upload_too_large`;
- `422 sha256_mismatch` or invalid ZIP;
- `429 rate_limit_exceeded`;
- `503 storage_unavailable`.

## History and administration

```http
GET /history
```

Each version includes `version`, `saveIdentity`, adapter-specific identity, `updatedBy`, `updatedAt`, `size`, `sha256`, `baseVersion` and `restoredFromVersion`.

Administrative operations:

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

Restore publishes a **new increasing version** with the same save identity.

Creating a token returns its plaintext value once. History download/restore/delete, force-unlock, token management and audit endpoints require `admin`; normal game operations accept `admin` or `player`.

## External-backup status

```http
GET /backup-status
```

Representative response:

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
  }
}
```

`state` may be `not_initialized`, `disabled`, `pending`, `completed`, `failed` or `unknown`.

Important semantics:

- `enabled` is the **current configuration** and is independent from the historical result of the current version;
- `pending_backups` is a durable queue, not an expiring marker table;
- `stalePending` is diagnostic only and does not authorize retention to delete the protected ZIP;
- `latestVersionBackedUp=true` means the supervisor audited a successful hook result for the current version;
- the endpoint does **not** query restic or prove that a remote snapshot still exists now;
- an uncertain crash can cause the hook to run again after restart, so the hook must tolerate at-least-once execution.

This endpoint is read-only and requires authentication but not the administrator role.

## curl examples

```bash
BASE=https://sync.example.com/api/games/palworld
TOKEN='pws_MACHINE_TOKEN'
AUTH="Authorization: Bearer ${TOKEN}"

curl --fail-with-body -H "$AUTH" -H 'Accept: application/json' \
  "$BASE/status"

curl --fail-with-body -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  --data '{"owner":"Host A","clientId":"host-a-pc"}' \
  "$BASE/lock"
```

After acquiring a lock:

```bash
SESSION='SESSION_RETURNED_BY_LOCK'
curl --fail-with-body -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  --data "{\"sessionId\":\"${SESSION}\"}" \
  "$BASE/heartbeat"

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
```

## Palworld compatibility aliases

The Palworld descriptor temporarily enables historical aliases under `/api/palworld/*`, `/palworld/api/*` and `/palworld`. New clients and deployments should use `/api/games/palworld` and `/games/palworld`.

## HTTP status summary

```text
200 success
201 resource/version created
400 invalid request
401 missing/invalid authentication
403 insufficient permission or HTTPS required
404 resource not found
409 lock/session/version/identity conflict
413 upload too large
422 hash or ZIP invalid
429 rate limit
500 internal error
503 storage unavailable
```
