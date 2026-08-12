#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY="${SAVE_SYNC_GITHUB_REPOSITORY:-Ayerdi/dedicated-server-save-sync}"

if [[ "${1:-}" != "--apply" || $# -ne 1 ]]; then
  printf 'Uso: %s --apply\n' "$0" >&2
  exit 2
fi

command -v gh >/dev/null || { printf 'GitHub CLI (gh) is required.\n' >&2; exit 1; }
command -v git >/dev/null || { printf 'git is required.\n' >&2; exit 1; }
cd "${ROOT_DIR}"

gh auth status >/dev/null 2>&1 || {
  printf 'GitHub CLI has no valid session. Run gh auth login.\n' >&2
  exit 1
}
[[ -d wiki ]] || { printf 'wiki/ directory is missing.\n' >&2; exit 1; }
[[ -z "$(git status --short)" ]] || {
  printf 'The Git tree must be clean; the Wiki never publishes uncommitted changes.\n' >&2
  exit 1
}
[[ "$(git branch --show-current)" == "main" ]] || {
  printf 'Sincroniza la Wiki desde main.\n' >&2
  exit 1
}

git fetch --quiet origin main
head_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse origin/main)"
if [[ "${head_sha}" != "${remote_sha}" ]]; then
  printf 'HEAD does not match origin/main. Update the checkout before publishing the Wiki.\n' >&2
  exit 1
fi

ci_state="$(gh run list --repo "${REPOSITORY}" --workflow ci.yml --branch main --limit 1 \
  --json headSha,status,conclusion \
  --jq '.[0] | (.headSha // "") + ":" + (.status // "") + ":" + (.conclusion // "")')"
if [[ "${ci_state}" != "${head_sha}:completed:success" ]]; then
  printf 'Main CI is not green for the current HEAD (%s).\n' "${ci_state:-no run}" >&2
  exit 1
fi

visibility="$(gh repo view "${REPOSITORY}" --json visibility --jq .visibility)"
if [[ "${visibility}" != "PUBLIC" ]]; then
  printf 'The public Wiki is synchronized only after the repository is public.\n' >&2
  exit 1
fi

wiki_enabled="$(gh repo view "${REPOSITORY}" --json hasWikiEnabled --jq .hasWikiEnabled)"
if [[ "${wiki_enabled}" != "true" ]]; then
  printf 'Enable the repository Wiki before synchronizing it.\n' >&2
  exit 1
fi

TEMP_DIR="$(mktemp -d /tmp/save-sync-wiki.XXXXXX)"
trap 'rm -rf -- "${TEMP_DIR}"' EXIT

gh auth setup-git >/dev/null
WIKI_URL="https://github.com/${REPOSITORY}.wiki.git"

if ! git clone --quiet "${WIKI_URL}" "${TEMP_DIR}/repo"; then
  cat >&2 <<'EOF'
GitHub has not initialized the Wiki repository yet.
Open the Wiki tab, create a minimal Home page and run again:
  bash scripts/publish-wiki.sh --apply
EOF
  exit 1
fi

find "${TEMP_DIR}/repo" -mindepth 1 -maxdepth 1 -type f -name '*.md' -delete
cp wiki/*.md "${TEMP_DIR}/repo/"

cd "${TEMP_DIR}/repo"
git add --all
if git diff --cached --quiet; then
  printf 'The Wiki is already synchronized.\n'
  exit 0
fi

git_user="$(gh api user --jq .login)"
git_user_id="$(gh api user --jq .id)"
git -c user.name="${git_user}" \
    -c user.email="${git_user_id}+${git_user}@users.noreply.github.com" \
    commit --quiet -m 'docs: sync public wiki'
git push --quiet origin HEAD

printf 'Wiki sincronizada desde el commit %s de main.\n' "${head_sha}"
