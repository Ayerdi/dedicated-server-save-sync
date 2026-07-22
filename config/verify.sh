#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PUBLIC_BASE_URL="${SAVE_SYNC_PUBLIC_BASE_URL:?Define SAVE_SYNC_PUBLIC_BASE_URL}"
GAME_KEY="${SAVE_SYNC_GAME_KEY:?Define SAVE_SYNC_GAME_KEY}"
[[ "${GAME_KEY}" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || exit 2
COMPOSE_PROJECT="${SAVE_SYNC_COMPOSE_PROJECT:-save-sync-${GAME_KEY}}"
CONTAINER_NAME="save_sync_${GAME_KEY}"

log() {
  printf '[save-sync-verify] %s\n' "$*"
}

cd "${PROJECT_DIR}"
docker compose -p "${COMPOSE_PROJECT}" config --quiet

health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${CONTAINER_NAME}")"
[[ "${health}" == "healthy" ]] || { log "Health inesperado: ${health}."; exit 1; }

published_ports="$(docker inspect --format '{{json .NetworkSettings.Ports}}' "${CONTAINER_NAME}")"
if [[ "${published_ports}" != '{"8080/tcp":null}' && "${published_ports}" != '{}' ]]; then
  log "El backend tiene una publicacion de puertos inesperada."
  exit 1
fi

api_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  "${PUBLIC_BASE_URL}/api/games/${GAME_KEY}/status")"
[[ "${api_status}" == "401" ]] || { log "La API sin Bearer devolvio ${api_status}, se esperaba 401."; exit 1; }

panel_headers="$(mktemp)"
trap 'rm -f -- "${panel_headers}"' EXIT
panel_status="$(curl --silent --show-error --output /dev/null --dump-header "${panel_headers}" --write-out '%{http_code}' \
  "${PUBLIC_BASE_URL}/games/${GAME_KEY}")"
case "${panel_status}" in
  301|302|303|307|308) ;;
  *) log "El panel anonimo devolvio ${panel_status}, se esperaba redireccion Authentik."; exit 1 ;;
esac
if ! grep -Eiq '^location: .+' "${panel_headers}"; then
  log "La redireccion del panel no incluye Location."
  exit 1
fi

log "OK: backend healthy, sin puertos publicados, API=401 y panel protegido por Authentik."
