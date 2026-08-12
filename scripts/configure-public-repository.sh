#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY="${SAVE_SYNC_GITHUB_REPOSITORY:-Ayerdi/dedicated-server-save-sync}"
PAGES_URL="${SAVE_SYNC_PAGES_URL:-https://ayerdi.github.io/dedicated-server-save-sync/}"
RELEASE_VERSION="2.2.1"
RELEASE_TAG="v${RELEASE_VERSION}"
RELEASE_ZIP="dedicated-server-save-sync-client-v${RELEASE_VERSION}.zip"
RELEASE_CHECKSUM="${RELEASE_ZIP}.sha256"
RELEASE_ZIP_DIGEST="sha256:4ee67ecdb617374c74f39db3819d6a6dae50618111102fa8a196c3f2beceacfc"

if [[ "${1:-}" != "--apply" || $# -ne 1 ]]; then
  printf 'Uso: %s --apply\n' "$0" >&2
  printf 'Run this only after manually changing repository visibility to public.\n' >&2
  exit 2
fi

command -v gh >/dev/null || { printf 'GitHub CLI (gh) is required.\n' >&2; exit 1; }
command -v git >/dev/null || { printf 'git is required.\n' >&2; exit 1; }
cd "${ROOT_DIR}"

gh auth status >/dev/null 2>&1 || {
  printf 'GitHub CLI has no valid session. Run gh auth login.\n' >&2
  exit 1
}

visibility="$(gh repo view "${REPOSITORY}" --json visibility --jq .visibility)"
if [[ "${visibility}" != "PUBLIC" ]]; then
  printf 'Abortado: %s sigue siendo %s. Este script nunca cambia la visibilidad.\n' \
    "${REPOSITORY}" "${visibility}" >&2
  exit 1
fi

[[ -f LICENSE ]] || { printf 'LICENSE is missing.\n' >&2; exit 1; }
[[ -z "$(git status --short)" ]] || {
  printf 'The Git tree must be clean before configuring GitHub.\n' >&2
  exit 1
}
[[ "$(git branch --show-current)" == "main" ]] || {
  printf 'Run repository configuration from the main branch.\n' >&2
  exit 1
}

git fetch --quiet origin main --tags
head_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse origin/main)"
if [[ "${head_sha}" != "${remote_sha}" ]]; then
  printf 'HEAD (%s) does not match origin/main (%s). Update the checkout.\n' \
    "${head_sha}" "${remote_sha}" >&2
  exit 1
fi

tag_commit="$(git rev-list -n1 "${RELEASE_TAG}" 2>/dev/null || true)"
if [[ -z "${tag_commit}" ]]; then
  printf 'The audited tag does not exist: %s.\n' "${RELEASE_TAG}" >&2
  exit 1
fi
if ! git merge-base --is-ancestor "${tag_commit}" "${head_sha}"; then
  printf 'El tag %s (%s) is not an ancestor of the current main (%s).\n' \
    "${RELEASE_TAG}" "${tag_commit}" "${head_sha}" >&2
  exit 1
fi

ci_state="$(gh run list --repo "${REPOSITORY}" --workflow ci.yml --branch main --limit 1 \
  --json headSha,status,conclusion \
  --jq '.[0] | (.headSha // "") + ":" + (.status // "") + ":" + (.conclusion // "")')"
if [[ "${ci_state}" != "${head_sha}:completed:success" ]]; then
  printf 'The latest main CI is not green for HEAD %s (%s).\n' \
    "${head_sha}" "${ci_state:-no run}" >&2
  exit 1
fi

release_api="repos/${REPOSITORY}/releases/tags/${RELEASE_TAG}"
release_target="$(gh api "${release_api}" --jq '.target_commitish // ""')"
release_draft="$(gh api "${release_api}" --jq '.draft')"
release_prerelease="$(gh api "${release_api}" --jq '.prerelease')"
release_assets="$(gh api "${release_api}" --jq '[.assets[].name] | sort | join(",")')"
zip_digest="$(gh api "${release_api}" --jq ".assets[] | select(.name == \"${RELEASE_ZIP}\") | (.digest // \"\")")"
expected_assets="$(printf '%s\n%s\n' "${RELEASE_ZIP}" "${RELEASE_CHECKSUM}" | sort | paste -sd, -)"

if [[ "${release_target}" != "${tag_commit}" || \
      "${release_draft}" != "false" || "${release_prerelease}" != "false" || \
      "${release_assets}" != "${expected_assets}" || \
      "${zip_digest}" != "${RELEASE_ZIP_DIGEST}" ]]; then
  cat >&2 <<EOF
Release ${RELEASE_TAG} does not match the audited candidate.
  tag commit: ${tag_commit}
  release target: ${release_target}
  draft/prerelease: ${release_draft}/${release_prerelease}
  assets: ${release_assets}
  ZIP digest: ${zip_digest}
  esperado: ${RELEASE_ZIP_DIGEST}
Public repository configuration will not be applied.
EOF
  exit 1
fi

gh api --method PATCH "repos/${REPOSITORY}" \
  -f description='Concurrency-safe Palworld save synchronization for alternating dedicated-server hosts' \
  -f homepage="${PAGES_URL}" \
  -F has_issues=true \
  -F has_discussions=true \
  -F has_wiki=true \
  -F delete_branch_on_merge=true >/dev/null

gh api --method PUT "repos/${REPOSITORY}/topics" \
  -f 'names[]=palworld' \
  -f 'names[]=dedicated-server' \
  -f 'names[]=game-server' \
  -f 'names[]=save-sync' \
  -f 'names[]=self-hosted' \
  -f 'names[]=backup' \
  -f 'names[]=docker' \
  -f 'names[]=flask' \
  -f 'names[]=powershell' >/dev/null

gh api --method PUT "repos/${REPOSITORY}/vulnerability-alerts" >/dev/null
gh api --method PUT "repos/${REPOSITORY}/private-vulnerability-reporting" >/dev/null

gh api --method PUT "repos/${REPOSITORY}/branches/main/protection" \
  --input - >/dev/null <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      {"context": "backend"},
      {"context": "integration"},
      {"context": "powershell"},
      {"context": "secrets"}
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

if ! gh api "repos/${REPOSITORY}/pages" >/dev/null 2>&1; then
  gh api --method POST "repos/${REPOSITORY}/pages" \
    -f build_type=workflow >/dev/null
fi
gh api --method PUT "repos/${REPOSITORY}/pages" \
  -f build_type=workflow \
  -F https_enforced=true >/dev/null

printf 'Public repository configuration applied to %s.\n' "${REPOSITORY}"
printf 'Release %s verificada: %s\n' "${RELEASE_TAG}" "${RELEASE_ZIP_DIGEST}"
printf 'GitHub Pages: %s\n' "${PAGES_URL}"
printf 'Dispatching Pages deployment...\n'
gh workflow run pages.yml --repo "${REPOSITORY}" --ref main

printf '\nWiki enabled. To synchronize the versioned content run:\n'
printf '  bash scripts/publish-wiki.sh --apply\n'
