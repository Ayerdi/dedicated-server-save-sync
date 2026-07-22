#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="save-sync-local-e2e"
LOCAL_PORT="${SAVE_SYNC_LOCAL_PORT:-18080}"
export SAVE_SYNC_LOCAL_PORT="${LOCAL_PORT}"
export SAVE_SYNC_LOCAL_ENV_FILE=".env.local.example"
export SAVE_SYNC_CONTAINER_NAME="save_sync_local_e2e"
export SAVE_SYNC_LOCAL_NETWORK="save-sync-local-e2e"
export SAVE_SYNC_LOCAL_VOLUME="save-sync-local-e2e-data"

compose=(
  docker compose
  --project-directory "${ROOT_DIR}"
  -p "${PROJECT_NAME}"
  -f "${ROOT_DIR}/docker-compose.yml"
  -f "${ROOT_DIR}/docker-compose.local.yml"
)

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "${TEMP_DIR:-}"
}
trap cleanup EXIT

TEMP_DIR="$(mktemp -d /tmp/save-sync-local-e2e.XXXXXX)"
BASE_URL="http://127.0.0.1:${LOCAL_PORT}/api/games/palworld"
AUTH_HEADER="Authorization: Bearer local-development-token"
WORLD_GUID="A7E97BAA767DB9029EF013BB71E993A0"
OTHER_GUID="B8F08CBB878ECA13AF1024CC82FAA4B1"

cd "${ROOT_DIR}"
"${compose[@]}" up --detach --build --wait

status_json="$(curl --fail-with-body --silent --show-error -H "${AUTH_HEADER}" "${BASE_URL}/status")"
python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["initialized"] is False and value["version"] == 0' <<<"${status_json}"

lock_json="$(curl --fail-with-body --silent --show-error -X POST \
  -H "${AUTH_HEADER}" -H 'Content-Type: application/json' \
  --data '{"owner":"Local Host","clientId":"local-e2e"}' "${BASE_URL}/lock")"
session_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["sessionId"])' <<<"${lock_json}")"

python3 - "${TEMP_DIR}/save.zip" <<'PY'
import pathlib
import sys
import zipfile

target = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("Pal/Saved/SaveGames/local-e2e.sav", b"public-readiness-e2e")
PY
archive_hash="$(sha256sum "${TEMP_DIR}/save.zip" | cut -d' ' -f1)"

upload_json="$(curl --fail-with-body --silent --show-error -X POST \
  -H "${AUTH_HEADER}" \
  -F "file=@${TEMP_DIR}/save.zip;type=application/zip" \
  -F "sessionId=${session_id}" -F 'baseVersion=0' \
  -F "sha256=${archive_hash}" -F "worldGuid=${WORLD_GUID}" \
  "${BASE_URL}/upload")"
python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["version"] == 1 and value["worldGuid"] == sys.argv[1]' "${WORLD_GUID}" <<<"${upload_json}"

curl --fail-with-body --silent --show-error -H "${AUTH_HEADER}" \
  --dump-header "${TEMP_DIR}/download.headers" \
  --output "${TEMP_DIR}/download.zip" "${BASE_URL}/download"
download_hash="$(sha256sum "${TEMP_DIR}/download.zip" | cut -d' ' -f1)"
[[ "${download_hash}" == "${archive_hash}" ]]
grep -Fq "X-Palworld-World-Guid: ${WORLD_GUID}" "${TEMP_DIR}/download.headers"

curl --fail-with-body --silent --show-error -H "${AUTH_HEADER}" \
  --output "${TEMP_DIR}/history.zip" "${BASE_URL}/history/1/download"
[[ "$(sha256sum "${TEMP_DIR}/history.zip" | cut -d' ' -f1)" == "${archive_hash}" ]]

restore_json="$(curl --fail-with-body --silent --show-error -X POST \
  -H "${AUTH_HEADER}" "${BASE_URL}/history/1/restore")"
python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["version"] == 2 and value["restoredFromVersion"] == 1' <<<"${restore_json}"

lock_json="$(curl --fail-with-body --silent --show-error -X POST \
  -H "${AUTH_HEADER}" -H 'Content-Type: application/json' \
  --data '{"owner":"Local Host","clientId":"local-e2e"}' "${BASE_URL}/lock")"
session_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["sessionId"])' <<<"${lock_json}")"
conflict_code="$(curl --silent --show-error --output "${TEMP_DIR}/conflict.json" \
  --write-out '%{http_code}' -X POST -H "${AUTH_HEADER}" \
  -F "file=@${TEMP_DIR}/save.zip;type=application/zip" \
  -F "sessionId=${session_id}" -F 'baseVersion=2' \
  -F "sha256=${archive_hash}" -F "worldGuid=${OTHER_GUID}" \
  "${BASE_URL}/upload")"
[[ "${conflict_code}" == "409" ]]
python3 -c 'import json,sys; assert json.load(open(sys.argv[1], encoding="utf-8"))["error"] == "world_guid_conflict"' "${TEMP_DIR}/conflict.json"

curl --fail-with-body --silent --show-error -X POST \
  -H "${AUTH_HEADER}" -H 'Content-Type: application/json' \
  --data "{\"sessionId\":\"${session_id}\"}" "${BASE_URL}/unlock" >/dev/null

final_json="$(curl --fail-with-body --silent --show-error -H "${AUTH_HEADER}" "${BASE_URL}/status")"
python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["version"] == 2 and value["locked"] is False' <<<"${final_json}"

printf 'E2E local OK: bootstrap, lock, upload, download, restore, conflicto de mundo y unlock.\n'
