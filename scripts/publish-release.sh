#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY="${SAVE_SYNC_GITHUB_REPOSITORY:-Ayerdi/dedicated-server-save-sync}"
VERSION="${1:-}"
APPLY="${2:-}"

if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ || "${APPLY}" != "--apply" || $# -ne 2 ]]; then
  printf 'Usage: %s MAJOR.MINOR.PATCH --apply\n' "$0" >&2
  exit 2
fi

command -v gh >/dev/null || { printf 'GitHub CLI (gh) is required.\n' >&2; exit 1; }
command -v git >/dev/null || { printf 'git is required.\n' >&2; exit 1; }
cd "${ROOT_DIR}"

gh auth status >/dev/null 2>&1 || {
  printf 'GitHub CLI has no valid session. Run gh auth login.\n' >&2
  exit 1
}
[[ -z "$(git status --short)" ]] || {
  printf 'The Git tree must be clean before publishing a release.\n' >&2
  exit 1
}
[[ "$(git branch --show-current)" == "main" ]] || {
  printf 'Stable releases can only be published from main.\n' >&2
  exit 1
}

git fetch --quiet origin main --tags
head_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse origin/main)"
if [[ "${head_sha}" != "${remote_sha}" ]]; then
  printf 'HEAD does not match origin/main. Update the checkout.\n' >&2
  exit 1
fi

ci_state="$(gh run list --repo "${REPOSITORY}" --workflow ci.yml --branch main --limit 1 \
  --json headSha,status,conclusion \
  --jq '.[0] | (.headSha // "") + ":" + (.status // "") + ":" + (.conclusion // "")')"
if [[ "${ci_state}" != "${head_sha}:completed:success" ]]; then
  printf 'Main CI is not green for HEAD %s (%s).\n' \
    "${head_sha}" "${ci_state:-no run}" >&2
  exit 1
fi

notes="docs/RELEASE-NOTES-v${VERSION}.md"
[[ -f "${notes}" ]] || {
  printf 'Versioned release notes are missing: %s\n' "${notes}" >&2
  exit 1
}
grep -Fq "## ${VERSION}" CHANGELOG.md || {
  printf 'CHANGELOG.md does not contain a ## section for %s.\n' "${VERSION}" >&2
  exit 1
}

if gh release view "v${VERSION}" --repo "${REPOSITORY}" >/dev/null 2>&1; then
  printf 'Release v%s already exists; it will not be overwritten.\n' "${VERSION}" >&2
  exit 1
fi
if git show-ref --verify --quiet "refs/tags/v${VERSION}" || \
   git ls-remote --exit-code --tags origin "refs/tags/v${VERSION}" >/dev/null 2>&1; then
  printf 'Tag v%s already exists; review it manually before publishing.\n' "${VERSION}" >&2
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
  printf 'WARNING: GitHub returned an unexpected ZIP digest: %s\n' \
    "${uploaded_digest:-empty}" >&2
  printf 'The release exists and must be reviewed manually before announcing it.\n' >&2
  exit 1
fi

printf 'Release v%s published from %s after two reproducible builds.\n' \
  "${VERSION}" "${head_sha}"
printf 'Published digest: %s\n' "${uploaded_digest}"
