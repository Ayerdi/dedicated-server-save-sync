#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${SCRIPT_DIR}/runtime"
TEMPLATE_PATH=""
RUNTIME_ROUTE=""
PREVIOUS_ROUTE=""
COMPOSE_PROJECT=""
CONTAINER_NAME=""
BACKUP_CONTAINER_NAME=""
route_published=0
had_previous=0

log() {
  printf '[save-sync-deploy] %s\n' "$*"
}

usage() {
  cat <<'EOF'
Uso:
  config/deploy.sh             Despliega usando un .env existente.
  config/deploy.sh --init-env  Crea .env de forma segura y termina sin desplegar.
EOF
}

init_env() {
  local example_path="${PROJECT_DIR}/.env.example"
  local env_path="${PROJECT_DIR}/.env"

  [[ -f "${example_path}" ]] || { log "Falta ${example_path}."; return 1; }
  if [[ -e "${env_path}" ]]; then
    log "${env_path} ya existe; no se ha sobrescrito."
    return 1
  fi

  python3 - "${example_path}" "${env_path}" <<'PY'
import os
import pathlib
import re
import secrets
import sys
import tempfile

example_path = pathlib.Path(sys.argv[1])
env_path = pathlib.Path(sys.argv[2])
source = example_path.read_text(encoding="utf-8")
keys = ("SAVE_SYNC_PROXY_SECRET", "SAVE_SYNC_CSRF_SECRET")

for key in keys:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if len(pattern.findall(source)) != 1:
        raise SystemExit(f".env.example debe contener exactamente una linea {key}")
    source = pattern.sub(f"{key}={secrets.token_hex(32)}", source)

fd, temporary_name = tempfile.mkstemp(prefix=".env.init.", dir=env_path.parent)
temporary_path = pathlib.Path(temporary_name)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(source)
        handle.flush()
        os.fsync(handle.fileno())
    # link() es atomico y falla si otro proceso ha creado .env: nunca sobrescribe.
    os.link(temporary_path, env_path)
    directory_fd = os.open(env_path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
except FileExistsError:
    raise SystemExit(".env ya existe; no se ha sobrescrito")
finally:
    temporary_path.unlink(missing_ok=True)
PY

  log "Creado ${env_path} con permisos 0600 y secretos aleatorios locales."
  log "Revisa los valores no secretos antes de ejecutar el despliegue."
}

restore_route_on_error() {
  local exit_code=$?
  if (( route_published )); then
    log "La verificacion fallo; restaurando la ruta Traefik anterior."
    if (( had_previous )); then
      local restore_tmp
      restore_tmp="$(mktemp "${TRAEFIK_DYNAMIC_DIR}/.save-sync-restore.XXXXXX")"
      install -m 0600 "${PREVIOUS_ROUTE}" "${restore_tmp}"
      mv -f -- "${restore_tmp}" "${TRAEFIK_ROUTE}"
    else
      local disabled_route="${RUNTIME_DIR}/save-sync-${GAME_KEY}.failed.$(date -u +%Y%m%dT%H%M%SZ).yml"
      mv -- "${TRAEFIK_ROUTE}" "${disabled_route}"
      chmod 0600 "${disabled_route}"
    fi
  fi
  exit "${exit_code}"
}
trap restore_route_on_error ERR

command -v python3 >/dev/null

case "${1:-}" in
  --init-env)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    init_env
    trap - ERR
    exit 0
    ;;
  -h|--help)
    usage
    trap - ERR
    exit 0
    ;;
  "") ;;
  *)
    usage >&2
    exit 2
    ;;
esac

command -v docker >/dev/null
command -v curl >/dev/null
docker compose version >/dev/null

[[ -f "${PROJECT_DIR}/.env" ]] || { log "Falta ${PROJECT_DIR}/.env; parte de .env.example."; exit 1; }
env_value() {
  python3 - "${PROJECT_DIR}/.env" "$1" <<'PY'
import pathlib
import re
import sys

path, wanted = pathlib.Path(sys.argv[1]), sys.argv[2]
for raw in path.read_text(encoding="utf-8").splitlines():
    match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)", raw.strip())
    if not match or match.group(1) != wanted:
        continue
    value = match.group(2).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    print(value)
    break
PY
}

TRAEFIK_DYNAMIC_DIR="${SAVE_SYNC_TRAEFIK_DYNAMIC_DIR:-$(env_value SAVE_SYNC_TRAEFIK_DYNAMIC_DIR)}"
PUBLIC_BASE_URL="${SAVE_SYNC_PUBLIC_BASE_URL:-$(env_value SAVE_SYNC_PUBLIC_BASE_URL)}"
GAME_KEY="${SAVE_SYNC_GAME_KEY:-$(env_value SAVE_SYNC_GAME_KEY)}"
PANEL_MODE="${SAVE_SYNC_PANEL_MODE:-$(env_value SAVE_SYNC_PANEL_MODE)}"
[[ "${GAME_KEY}" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || { log "SAVE_SYNC_GAME_KEY no es válido."; exit 1; }
case "${PANEL_MODE}" in
  authentik) TEMPLATE_PATH="${SCRIPT_DIR}/save-sync.yml.template" ;;
  disabled) TEMPLATE_PATH="${SCRIPT_DIR}/save-sync-api-only.yml.template" ;;
  *) log "SAVE_SYNC_PANEL_MODE debe ser authentik o disabled."; exit 1 ;;
esac
[[ -f "${TEMPLATE_PATH}" ]] || { log "Falta la plantilla Traefik."; exit 1; }
[[ -n "${TRAEFIK_DYNAMIC_DIR}" ]] || { log "Falta SAVE_SYNC_TRAEFIK_DYNAMIC_DIR."; exit 1; }
[[ -n "${PUBLIC_BASE_URL}" ]] || { log "Falta SAVE_SYNC_PUBLIC_BASE_URL."; exit 1; }
GAME_CONFIG_PATH="${PROJECT_DIR}/config/games/${GAME_KEY}.json"
[[ -f "${GAME_CONFIG_PATH}" ]] || { log "Falta ${GAME_CONFIG_PATH}."; exit 1; }
COMPOSE_PROJECT="${SAVE_SYNC_COMPOSE_PROJECT:-save-sync-${GAME_KEY}}"
CONTAINER_NAME="save_sync_${GAME_KEY}"
BACKUP_CONTAINER_NAME="save_sync_${GAME_KEY}_backup"
export SAVE_SYNC_CONTAINER_NAME="${CONTAINER_NAME}"
export SAVE_SYNC_BACKUP_CONTAINER_NAME="${BACKUP_CONTAINER_NAME}"
RUNTIME_ROUTE="${RUNTIME_DIR}/save-sync-${GAME_KEY}.yml"
PREVIOUS_ROUTE="${RUNTIME_DIR}/save-sync-${GAME_KEY}.previous.yml"
TRAEFIK_ROUTE="${TRAEFIK_DYNAMIC_DIR}/save-sync-${GAME_KEY}.yml"
[[ -d "${TRAEFIK_DYNAMIC_DIR}" ]] || { log "No existe ${TRAEFIK_DYNAMIC_DIR}."; exit 1; }

mkdir -p "${RUNTIME_DIR}"
chmod 0700 "${RUNTIME_DIR}"

log "Validando configuracion privada y generando ruta runtime."
python3 "${SCRIPT_DIR}/render_route.py" \
  --env "${PROJECT_DIR}/.env" \
  --template "${TEMPLATE_PATH}" \
  --output "${RUNTIME_ROUTE}" \
  --game "${GAME_CONFIG_PATH}"

env_mode="$(stat -c '%a' "${PROJECT_DIR}/.env")"
if [[ "${env_mode}" != "600" && "${env_mode}" != "400" ]]; then
  log "El archivo .env debe tener permisos 0600 o 0400 (actual: ${env_mode})."
  exit 1
fi

cd "${PROJECT_DIR}"
log "Validando y construyendo el stack aislado."
docker compose -p "${COMPOSE_PROJECT}" config --quiet
docker compose -p "${COMPOSE_PROJECT}" build --pull

log "Preparando el volumen privado con UID 10001."
# Estas capacidades se conceden solo al contenedor efimero. CHOWN cambia el
# propietario; DAC_OVERRIDE permite recorrer un arbol 0700 de UID 10001 en
# redespliegues y FOWNER permite corregir sus modos. El servicio final mantiene
# cap_drop: ALL en docker-compose.yml.
docker compose -p "${COMPOSE_PROJECT}" run --rm --no-deps --user 0 \
  --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER dedicated-server-save-sync \
  sh -eu -c 'mkdir -p /data/save-sync/backups /data/save-sync/temporary && chown -R 10001:10001 /data/save-sync && chmod 0700 /data/save-sync /data/save-sync/backups /data/save-sync/temporary'

log "Levantando backend y supervisor durable para ${GAME_KEY}."
docker compose -p "${COMPOSE_PROJECT}" up -d --wait

health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${CONTAINER_NAME}")"
[[ "${health}" == "healthy" ]] || { log "El backend no esta healthy: ${health}."; exit 1; }
backup_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${BACKUP_CONTAINER_NAME}")"
[[ "${backup_health}" == "healthy" ]] || {
  log "El supervisor de backup no esta healthy: ${backup_health}."
  docker compose -p "${COMPOSE_PROJECT}" logs --no-color --tail=100 backup-supervisor >&2 || true
  exit 1
}

if [[ -f "${TRAEFIK_ROUTE}" ]]; then
  install -m 0600 "${TRAEFIK_ROUTE}" "${PREVIOUS_ROUTE}"
  had_previous=1
else
  rm -f -- "${PREVIOUS_ROUTE}"
fi

log "Publicando la ruta Traefik mediante rename atomico."
route_tmp="$(mktemp "${TRAEFIK_DYNAMIC_DIR}/.save-sync-route.XXXXXX")"
install -m 0600 "${RUNTIME_ROUTE}" "${route_tmp}"
mv -f -- "${route_tmp}" "${TRAEFIK_ROUTE}"
route_published=1

sleep 2
SAVE_SYNC_PUBLIC_BASE_URL="${PUBLIC_BASE_URL}" SAVE_SYNC_GAME_KEY="${GAME_KEY}" SAVE_SYNC_PANEL_MODE="${PANEL_MODE}" "${SCRIPT_DIR}/verify.sh"
route_published=0
trap - ERR
log "Despliegue verificado. Backend y supervisor estan healthy; no se ha reiniciado Traefik."