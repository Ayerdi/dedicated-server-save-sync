#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY="${SAVE_SYNC_GITHUB_REPOSITORY:-Ayerdi/dedicated-server-save-sync}"
VERSION="${1:-}"
APPLY="${2:-}"

if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ || "${APPLY}" != "--apply" || $# -ne 2 ]]; then
  printf 'Uso: %s MAJOR.MINOR.PATCH --apply\n' "$0" >&2
  exit 2
fi

command -v gh >/dev/null || { printf 'Falta GitHub CLI (gh).\n' >&2; exit 1; }
command -v git >/dev/null || { printf 'Falta git.\n' >&2; exit 1; }
cd "${ROOT_DIR}"

gh auth status >/dev/null 2>&1 || {
  printf 'GitHub CLI no tiene una sesión válida. Ejecuta gh auth login.\n' >&2
  exit 1
}
[[ -z "$(git status --short)" ]] || {
  printf 'El árbol Git debe estar limpio antes de publicar una release.\n' >&2
  exit 1
}
[[ "$(git branch --show-current)" == "main" ]] || {
  printf 'Las releases estables solo se publican desde main.\n' >&2
  exit 1
}

git fetch --quiet origin main --tags
head_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse origin/main)"
if [[ "${head_sha}" != "${remote_sha}" ]]; then
  printf 'HEAD no coincide con origin/main. Actualiza el checkout.\n' >&2
  exit 1
fi

ci_state="$(gh run list --repo "${REPOSITORY}" --workflow ci.yml --branch main --limit 1 \
  --json headSha,status,conclusion \
  --jq '.[0] | (.headSha // "") + ":" + (.status // "") + ":" + (.conclusion // "")')"
if [[ "${ci_state}" != "${head_sha}:completed:success" ]]; then
  printf 'La CI de main no está verde para HEAD %s (%s).\n' \
    "${head_sha}" "${ci_state:-sin ejecución}" >&2
  exit 1
fi

notes="docs/RELEASE-NOTES-v${VERSION}.md"
[[ -f "${notes}" ]] || {
  printf 'Faltan las notas versionadas: %s\n' "${notes}" >&2
  exit 1
}
grep -Fq "## ${VERSION}" CHANGELOG.md || {
  printf 'CHANGELOG.md no contiene una sección ## %s.\n' "${VERSION}" >&2
  exit 1
}

if gh release view "v${VERSION}" --repo "${REPOSITORY}" >/dev/null 2>&1; then
  printf 'La release v%s ya existe; no se sobrescribe.\n' "${VERSION}" >&2
  exit 1
fi
if git show-ref --verify --quiet "refs/tags/v${VERSION}" || \
   git ls-remote --exit-code --tags origin "refs/tags/v${VERSION}" >/dev/null 2>&1; then
  printf 'El tag v%s ya existe; revísalo manualmente antes de publicar.\n' "${VERSION}" >&2
  exit 1
fi

bash scripts/check-repository.sh
bash scripts/build-release.sh "${VERSION}"
archive="dist/dedicated-server-save-sync-client-v${VERSION}.zip"
checksum="${archive}.sha256"
first="$(cut -d' ' -f1 "${checksum}")"
first_copy="$(mktemp /tmp/save-sync-release.XXXXXX.zip)"
trap 'rm -f -- "${first_copy}"' EXIT
cp "${archive}" "${first_copy}"
rm -f "${archive}" "${checksum}"
bash scripts/build-release.sh "${VERSION}"
second="$(cut -d' ' -f1 "${checksum}")"
test "${first}" = "${second}"
cmp "${first_copy}" "${archive}"

release_title="${SAVE_SYNC_RELEASE_TITLE:-v${VERSION}}"
gh release create "v${VERSION}" \
  "${archive}" \
  "${checksum}" \
  --repo "${REPOSITORY}" \
  --target "${head_sha}" \
  --title "${release_title}" \
  --notes-file "${notes}"

uploaded_digest="$(gh api "repos/${REPOSITORY}/releases/tags/v${VERSION}" \
  --jq ".assets[] | select(.name == \"$(basename "${archive}")\") | (.digest // \"\")")"
if [[ "${uploaded_digest}" != "sha256:${second}" ]]; then
  printf 'ATENCIÓN: GitHub devolvió digest inesperado para el ZIP: %s\n' \
    "${uploaded_digest:-vacío}" >&2
  printf 'La release existe y debe revisarse manualmente antes de anunciarla.\n' >&2
  exit 1
fi

printf 'Release v%s publicada desde %s tras doble build reproducible.\n' \
  "${VERSION}" "${head_sha}"
printf 'Digest publicado: %s\n' "${uploaded_digest}"
