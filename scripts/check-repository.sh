#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname -- "${BASH_SOURCE[0]}")/.."

tracked_files=()
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  mapfile -d '' tracked_files < <(
    git ls-files --cached --others --exclude-standard -z
  )
else
  mapfile -d '' tracked_files < <(
    find . -type f \
      -not -path './.git/*' \
      -not -path './.venv/*' \
      -not -path './data/*' \
      -not -path './client/data/*' -print0
  )
fi

if (( ${#tracked_files[@]} == 0 )); then
  printf 'No hay archivos para revisar.\n' >&2
  exit 1
fi

for file in "${tracked_files[@]}"; do
  normalized="${file#./}"
  case "${normalized}" in
    .env|.env.local|client/config.json)
      printf 'Archivo privado incluido: %s\n' "${normalized}" >&2
      exit 1
      ;;
  esac
done

if grep -IEn 'pws_[A-Za-z0-9_-]{48}|-----BEGIN ([A-Z ]+ )?PRIVATE KEY-----' \
  "${tracked_files[@]}" >/dev/null; then
  printf 'Posible token o clave privada detectado.\n' >&2
  exit 1
fi

if printf '%s\n' "${tracked_files[@]}" | grep -E \
  '(^|/)(data|config/runtime|client/data)/|\.(sav|sqlite3|sqlite3-wal|sqlite3-shm|zip)$' >/dev/null; then
  printf 'Artefacto runtime/save detectado.\n' >&2
  exit 1
fi

printf 'Repositorio sin patrones secretos ni artefactos runtime conocidos.\n'
