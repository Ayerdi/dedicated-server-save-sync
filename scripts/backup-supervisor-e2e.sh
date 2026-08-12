#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="save-sync-backup-recovery-e2e"
LOCAL_PORT="${SAVE_SYNC_BACKUP_E2E_PORT:-18081}"
TEMP_DIR="$(mktemp -d /tmp/save-sync-backup-recovery-e2e.XXXXXX)"
ENV_FILE="${TEMP_DIR}/e2e.env"

export SAVE_SYNC_LOCAL_PORT="${LOCAL_PORT}"
export SAVE_SYNC_LOCAL_ENV_FILE="${ENV_FILE}"
export SAVE_SYNC_CONTAINER_NAME="save_sync_backup_recovery_e2e"
export SAVE_SYNC_BACKUP_CONTAINER_NAME="save_sync_backup_recovery_e2e_supervisor"
export SAVE_SYNC_LOCAL_NETWORK="save-sync-backup-recovery-e2e"
export SAVE_SYNC_LOCAL_VOLUME="save-sync-backup-recovery-e2e-data"

compose=(
  docker compose
  --project-directory "${ROOT_DIR}"
  -p "${PROJECT_NAME}"
  -f "${ROOT_DIR}/docker-compose.yml"
  -f "${ROOT_DIR}/docker-compose.local.yml"
)

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "${TEMP_DIR}"
}
trap cleanup EXIT

cat >"${ENV_FILE}" <<'EOF'
SAVE_SYNC_GAME_KEY=palworld
SAVE_SYNC_GAME_CONFIG_PATH=/app/game.json
SAVE_SYNC_STORAGE_PATH=/data/save-sync
SAVE_SYNC_DB_PATH=/data/save-sync/save-sync.sqlite3
SAVE_SYNC_REQUIRE_HTTPS=false
SAVE_SYNC_WEB_USERS=local-admin:admin
SAVE_SYNC_USER_IDENTITIES_JSON={"local-admin":{"displayName":"Local Host","slot":"local-host"}}
SAVE_SYNC_PROXY_SECRET=local-proxy-secret-development-only-0001
SAVE_SYNC_CSRF_SECRET=local-csrf-secret-development-only-000001
SAVE_SYNC_BOOTSTRAP_TOKENS_JSON=[{"username":"local-admin","name":"backup-e2e","token":"local-development-token"}]
SAVE_SYNC_MAX_UPLOAD_SIZE=10485760
SAVE_SYNC_LOCK_TTL_SECONDS=300
SAVE_SYNC_HEARTBEAT_INTERVAL_SECONDS=60
SAVE_SYNC_RATE_LIMIT_PER_MINUTE=10000
SAVE_SYNC_RETENTION_PER_SLOT=1
SAVE_SYNC_POST_PUBLISH_COMMAND=python /app/backup-supervisor-e2e-hook.py
SAVE_SYNC_POST_PUBLISH_TIMEOUT_SECONDS=30
SAVE_SYNC_BACKUP_POLL_SECONDS=0.1
EOF

BASE_URL="http://127.0.0.1:${LOCAL_PORT}/api/games/palworld"
AUTH_HEADER="Authorization: Bearer local-development-token"
WORLD_GUID="A7E97BAA767DB9029EF013BB71E993A0"

cd "${ROOT_DIR}"
"${compose[@]}" up --detach --build --wait

wait_exec_file() {
  local path="$1"
  local deadline=$((SECONDS + 30))
  until "${compose[@]}" exec -T backup-supervisor test -f "${path}"; do
    if (( SECONDS >= deadline )); then
      printf 'Timeout esperando %s\n' "${path}" >&2
      "${compose[@]}" logs --no-color backup-supervisor >&2 || true
      return 1
    fi
    sleep 0.2
  done
}

wait_backup_completed() {
  local version="$1"
  local deadline=$((SECONDS + 30))
  while (( SECONDS < deadline )); do
    local value
    value="$(curl --fail-with-body --silent --show-error \
      -H "${AUTH_HEADER}" "${BASE_URL}/backup-status")"
    if python3 - "${version}" "${value}" <<'PY'
import json
import sys

version = int(sys.argv[1])
value = json.loads(sys.argv[2])
raise SystemExit(
    0
    if value["latestPublishedVersion"] == version
    and value["state"] == "completed"
    and value["latestVersionBackedUp"] is True
    and value["pending"] is False
    else 1
)
PY
    then
      return 0
    fi
    sleep 0.2
  done
  printf 'Timeout esperando backup completado v%s\n' "${version}" >&2
  curl --silent -H "${AUTH_HEADER}" "${BASE_URL}/backup-status" >&2 || true
  "${compose[@]}" logs --no-color backup-supervisor >&2 || true
  return 1
}

publish_version() {
  local marker="$1"
  local zip_path="${TEMP_DIR}/${marker}.zip"
  python3 - "${zip_path}" "${marker}" <<'PY'
import pathlib
import sys
import zipfile

target = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("Pal/Saved/SaveGames/recovery-e2e.sav", sys.argv[2].encode())
PY
  local archive_hash
  archive_hash="$(sha256sum "${zip_path}" | cut -d' ' -f1)"
  local lock_json session_id base_version
  lock_json="$(curl --fail-with-body --silent --show-error -X POST \
    -H "${AUTH_HEADER}" -H 'Content-Type: application/json' \
    --data "{\"owner\":\"Local Host\",\"clientId\":\"backup-e2e-${marker}\"}" \
    "${BASE_URL}/lock")"
  session_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["sessionId"])' <<<"${lock_json}")"
  base_version="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["baseVersion"])' <<<"${lock_json}")"
  curl --fail-with-body --silent --show-error -X POST \
    -H "${AUTH_HEADER}" \
    -F "file=@${zip_path};type=application/zip" \
    -F "sessionId=${session_id}" -F "baseVersion=${base_version}" \
    -F "sha256=${archive_hash}" -F "worldGuid=${WORLD_GUID}" \
    "${BASE_URL}/upload"
}

# Caso 1: el backup sigue vivo aunque desaparezca por completo el web/Gunicorn.
publish_version "worker-crash" >/dev/null
wait_exec_file "/data/save-sync/temporary/backup-e2e-started-v1-1"
supervisor_before="$("${compose[@]}" ps -q backup-supervisor)"
"${compose[@]}" kill dedicated-server-save-sync >/dev/null
"${compose[@]}" up --detach --wait dedicated-server-save-sync >/dev/null
supervisor_after="$("${compose[@]}" ps -q backup-supervisor)"
[[ -n "${supervisor_before}" && "${supervisor_before}" == "${supervisor_after}" ]]
"${compose[@]}" exec -T backup-supervisor \
  touch /data/save-sync/temporary/backup-e2e-release-v1
wait_backup_completed 1

# Caso 2: también el supervisor puede morir; la fila durable debe sobrevivir y
# ser reclamada por la nueva ejecución, que generará el intento 2. Docker puede
# reiniciar el mismo container-id, por eso se valida semántica, no runtime-id.
publish_version "supervisor-crash" >/dev/null
wait_exec_file "/data/save-sync/temporary/backup-e2e-started-v2-1"
"${compose[@]}" kill backup-supervisor >/dev/null || true
"${compose[@]}" up --detach --wait backup-supervisor >/dev/null
wait_exec_file "/data/save-sync/temporary/backup-e2e-started-v2-2"
wait_backup_completed 2

history_json="$(curl --fail-with-body --silent --show-error \
  -H "${AUTH_HEADER}" "${BASE_URL}/history")"
python3 - "${history_json}" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
assert [item["version"] for item in value["versions"]] == [2], value
PY

attempts="$("${compose[@]}" exec -T backup-supervisor \
  cat /data/save-sync/temporary/backup-e2e-attempt-v2)"
[[ "${attempts//$'\r'/}" == "2" ]]

printf 'E2E backup recovery OK: web crash independiente y supervisor crash retomado desde SQLite.\n'
