#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY="${SAVE_SYNC_GITHUB_REPOSITORY:-Ayerdi/dedicated-server-save-sync}"

if [[ "${1:-}" != "--apply" || $# -ne 1 ]]; then
  printf 'Uso: %s --apply\n' "$0" >&2
  exit 2
fi

command -v gh >/dev/null
command -v git >/dev/null

[[ -d "${ROOT_DIR}/wiki" ]] || {
  printf 'Falta el directorio wiki/.\n' >&2
  exit 1
}

visibility="$(gh repo view "${REPOSITORY}" --json visibility --jq .visibility)"
if [[ "${visibility}" != "PUBLIC" ]]; then
  printf 'La wiki pública se sincroniza únicamente después de abrir el repositorio.\n' >&2
  exit 1
fi

wiki_enabled="$(
  gh repo view "${REPOSITORY}" --json hasWikiEnabled --jq .hasWikiEnabled
)"
if [[ "${wiki_enabled}" != "true" ]]; then
  printf 'Activa la Wiki del repositorio antes de sincronizarla.\n' >&2
  exit 1
fi

TEMP_DIR="$(mktemp -d /tmp/save-sync-wiki.XXXXXX)"
trap 'rm -rf -- "${TEMP_DIR}"' EXIT

gh auth setup-git >/dev/null
WIKI_URL="https://github.com/${REPOSITORY}.wiki.git"

if ! git clone --quiet "${WIKI_URL}" "${TEMP_DIR}/repo"; then
  cat >&2 <<'EOF'
GitHub todavía no ha inicializado el repositorio de la Wiki.
Abre la pestaña Wiki, crea una página Home mínima y vuelve a ejecutar:
  bash scripts/publish-wiki.sh --apply
EOF
  exit 1
fi

find "${TEMP_DIR}/repo" -mindepth 1 -maxdepth 1 \
  -type f \( -name '*.md' -o -name '_Sidebar.md' -o -name '_Footer.md' \) -delete
cp "${ROOT_DIR}"/wiki/*.md "${TEMP_DIR}/repo/"

cd "${TEMP_DIR}/repo"
git add --all
if git diff --cached --quiet; then
  printf 'La Wiki ya está sincronizada.\n'
  exit 0
fi

git -c user.name='Ayerdi' \
    -c user.email='128999164+Ayerdi@users.noreply.github.com' \
    commit --quiet -m 'docs: sync public wiki'
git push --quiet origin HEAD

printf 'Wiki sincronizada desde wiki/.\n'
