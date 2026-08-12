#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY="${SAVE_SYNC_GITHUB_REPOSITORY:-Ayerdi/dedicated-server-save-sync}"
PAGES_URL="${SAVE_SYNC_PAGES_URL:-https://ayerdi.github.io/dedicated-server-save-sync/}"
RELEASE_COMMIT="b085453f4bdd39d7c336980b0a27ce79605aa7a2"
RELEASE_ZIP="dedicated-server-save-sync-client-v2.2.0.zip"
RELEASE_CHECKSUM="${RELEASE_ZIP}.sha256"
RELEASE_ZIP_DIGEST="sha256:4d07ce1eb70f79471dca8d5f1ed9c4d7a37aaebbf53f5668d84be2058a781494"

if [[ "${1:-}" != "--apply" || $# -ne 1 ]]; then
  printf 'Uso: %s --apply\n' "$0" >&2
  printf 'Solo debe ejecutarse después de cambiar manualmente la visibilidad a pública.\n' >&2
  exit 2
fi

command -v gh >/dev/null || { printf 'Falta GitHub CLI (gh).\n' >&2; exit 1; }
command -v git >/dev/null || { printf 'Falta git.\n' >&2; exit 1; }
cd "${ROOT_DIR}"

gh auth status >/dev/null 2>&1 || {
  printf 'GitHub CLI no tiene una sesión válida. Ejecuta gh auth login.\n' >&2
  exit 1
}

visibility="$(gh repo view "${REPOSITORY}" --json visibility --jq .visibility)"
if [[ "${visibility}" != "PUBLIC" ]]; then
  printf 'Abortado: %s sigue siendo %s. Este script nunca cambia la visibilidad.\n' \
    "${REPOSITORY}" "${visibility}" >&2
  exit 1
fi

[[ -f LICENSE ]] || { printf 'Falta LICENSE.\n' >&2; exit 1; }
[[ -z "$(git status --short)" ]] || {
  printf 'El árbol Git debe estar limpio antes de configurar GitHub.\n' >&2
  exit 1
}
[[ "$(git branch --show-current)" == "main" ]] || {
  printf 'Ejecuta la configuración desde la rama main.\n' >&2
  exit 1
}

git fetch --quiet origin main
head_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse origin/main)"
if [[ "${head_sha}" != "${remote_sha}" ]]; then
  printf 'HEAD (%s) no coincide con origin/main (%s). Actualiza el checkout.\n' \
    "${head_sha}" "${remote_sha}" >&2
  exit 1
fi

ci_state="$(gh run list --repo "${REPOSITORY}" --workflow ci.yml --branch main --limit 1 \
  --json headSha,status,conclusion \
  --jq '.[0] | (.headSha // "") + ":" + (.status // "") + ":" + (.conclusion // "")')"
if [[ "${ci_state}" != "${head_sha}:completed:success" ]]; then
  printf 'La CI más reciente de main no está verde para HEAD %s (%s).\n' \
    "${head_sha}" "${ci_state:-sin ejecución}" >&2
  exit 1
fi

release_api="repos/${REPOSITORY}/releases/tags/v2.2.0"
release_target="$(gh api "${release_api}" --jq '.target_commitish // ""')"
release_draft="$(gh api "${release_api}" --jq '.draft')"
release_prerelease="$(gh api "${release_api}" --jq '.prerelease')"
release_assets="$(gh api "${release_api}" --jq '[.assets[].name] | sort | join(",")')"
zip_digest="$(gh api "${release_api}" --jq ".assets[] | select(.name == \"${RELEASE_ZIP}\") | (.digest // \"\")")"
expected_assets="$(printf '%s\n%s\n' "${RELEASE_ZIP}" "${RELEASE_CHECKSUM}" | sort | paste -sd, -)"

if [[ "${release_target}" != "${RELEASE_COMMIT}" || \
      "${release_draft}" != "false" || "${release_prerelease}" != "false" || \
      "${release_assets}" != "${expected_assets}" || \
      "${zip_digest}" != "${RELEASE_ZIP_DIGEST}" ]]; then
  cat >&2 <<EOF
La release v2.2.0 no coincide con el candidato auditado.
  target: ${release_target}
  draft/prerelease: ${release_draft}/${release_prerelease}
  assets: ${release_assets}
  ZIP digest: ${zip_digest}
No se aplicará la configuración pública.
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

printf 'Configuración pública aplicada a %s.\n' "${REPOSITORY}"
printf 'Release v2.2.0 verificada: %s\n' "${RELEASE_ZIP_DIGEST}"
printf 'GitHub Pages: %s\n' "${PAGES_URL}"
printf 'Disparando despliegue de Pages...\n'
gh workflow run pages.yml --repo "${REPOSITORY}" --ref main

printf '\nWiki habilitada. Para sincronizar su contenido versionado ejecuta:\n'
printf '  bash scripts/publish-wiki.sh --apply\n'
