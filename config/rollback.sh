#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${SCRIPT_DIR}/runtime"

env_value() {
  python3 - "${PROJECT_DIR}/.env" "$1" <<'PY'
import pathlib
import re
import sys

path, wanted = pathlib.Path(sys.argv[1]), sys.argv[2]
for raw in path.read_text(encoding="utf-8").splitlines():
    match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)", raw.strip())
    if match and match.group(1) == wanted:
        print(match.group(2).strip().strip("\"'"))
        break
PY
}

[[ -f "${PROJECT_DIR}/.env" ]] || { echo "Falta .env" >&2; exit 1; }
GAME_KEY="${SAVE_SYNC_GAME_KEY:-$(env_value SAVE_SYNC_GAME_KEY)}"
TRAEFIK_DYNAMIC_DIR="${SAVE_SYNC_TRAEFIK_DYNAMIC_DIR:-$(env_value SAVE_SYNC_TRAEFIK_DYNAMIC_DIR)}"
[[ "${GAME_KEY}" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || exit 2
PREVIOUS_ROUTE="${RUNTIME_DIR}/save-sync-${GAME_KEY}.previous.yml"
TRAEFIK_ROUTE="${TRAEFIK_DYNAMIC_DIR}/save-sync-${GAME_KEY}.yml"
COMPOSE_PROJECT="${SAVE_SYNC_COMPOSE_PROJECT:-save-sync-${GAME_KEY}}"

log() {
  printf '[save-sync-rollback] %s\n' "$*"
}

mkdir -p "${RUNTIME_DIR}"
chmod 0700 "${RUNTIME_DIR}"

if [[ -f "${PREVIOUS_ROUTE}" ]]; then
  route_tmp="$(mktemp "${TRAEFIK_DYNAMIC_DIR}/.save-sync-rollback.XXXXXX")"
  trap 'rm -f -- "${route_tmp:-}"' EXIT
  install -m 0600 "${PREVIOUS_ROUTE}" "${route_tmp}"
  mv -f -- "${route_tmp}" "${TRAEFIK_ROUTE}"
  log "Restaurada la configuracion Traefik anterior."
elif [[ -f "${TRAEFIK_ROUTE}" ]]; then
  disabled_route="${RUNTIME_DIR}/save-sync-${GAME_KEY}.disabled.$(date -u +%Y%m%dT%H%M%SZ).yml"
  mv -- "${TRAEFIK_ROUTE}" "${disabled_route}"
  chmod 0600 "${disabled_route}"
  log "Ruta de ${GAME_KEY} retirada; el fichero queda conservado fuera del directorio dinamico."
else
  log "No habia una ruta de ${GAME_KEY} publicada."
fi

cd "${PROJECT_DIR}"
docker compose -p "${COMPOSE_PROJECT}" down --remove-orphans
log "Backend detenido sin eliminar volumenes ni datos; Traefik no se ha reiniciado."
