#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PUBLIC_BASE_URL="${SAVE_SYNC_PUBLIC_BASE_URL:?Define SAVE_SYNC_PUBLIC_BASE_URL}"
GAME_KEY="${SAVE_SYNC_GAME_KEY:?Define SAVE_SYNC_GAME_KEY}"
PANEL_MODE="${SAVE_SYNC_PANEL_MODE:-authentik}"
[[ "${GAME_KEY}" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || exit 2
COMPOSE_PROJECT="${SAVE_SYNC_COMPOSE_PROJECT:-save-sync-${GAME_KEY}}"
CONTAINER_NAME="save_sync_${GAME_KEY}"
export SAVE_SYNC_CONTAINER_NAME="${CONTAINER_NAME}"

log() {
  printf '[save-sync-verify] %s\n' "$*"
}

cd "${PROJECT_DIR}"
docker compose -p "${COMPOSE_PROJECT}" config --quiet

health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${CONTAINER_NAME}")"
[[ "${health}" == "healthy" ]] || { log "Health inesperado: ${health}."; exit 1; }

published_ports="$(docker inspect --format '{{json .NetworkSettings.Ports}}' "${CONTAINER_NAME}")"
if [[ "${published_ports}" != '{"8080/tcp":null}' && "${published_ports}" != '{}' ]]; then
  log "The backend exposes an unexpected host port."
  exit 1
fi

api_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  "${PUBLIC_BASE_URL}/api/games/${GAME_KEY}/status")"
[[ "${api_status}" == "401" ]] || { log "The API without a Bearer token returned ${api_status}; expected 401."; exit 1; }

if [[ "${PANEL_MODE}" == "authentik" ]]; then
  panel_headers="$(mktemp)"
  trap 'rm -f -- "${panel_headers}"' EXIT
  panel_status="$(curl --silent --show-error --output /dev/null --dump-header "${panel_headers}" --write-out '%{http_code}' \
    "${PUBLIC_BASE_URL}/games/${GAME_KEY}")"
  case "${panel_status}" in
    301|302|303|307|308) ;;
    *) log "The anonymous panel returned ${panel_status}; expected an Authentik redirect."; exit 1 ;;
  esac
  if ! grep -Eiq '^location: .+' "${panel_headers}"; then
    log "The panel redirect does not include a Location header."
    exit 1
  fi
  log "OK: backend healthy, no published host ports, API=401 and panel protected by Authentik."
else
  log "OK: backend healthy, sin puertos publicados y API=401; panel deshabilitado."
fi
