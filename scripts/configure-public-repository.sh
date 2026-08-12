#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${SAVE_SYNC_GITHUB_REPOSITORY:-Ayerdi/dedicated-server-save-sync}"
PAGES_URL="${SAVE_SYNC_PAGES_URL:-https://ayerdi.github.io/dedicated-server-save-sync/}"

if [[ "${1:-}" != "--apply" || $# -ne 1 ]]; then
  printf 'Uso: %s --apply\n' "$0" >&2
  printf 'Solo debe ejecutarse después de cambiar manualmente la visibilidad a pública.\n' >&2
  exit 2
fi

command -v gh >/dev/null
command -v git >/dev/null

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
  "allow_deletions": false
}
JSON

if gh api "repos/${REPOSITORY}/pages" >/dev/null 2>&1; then
  gh api --method PUT "repos/${REPOSITORY}/pages" \
    -f build_type=workflow \
    -F https_enforced=true >/dev/null
else
  gh api --method POST "repos/${REPOSITORY}/pages" \
    -f build_type=workflow >/dev/null
fi

printf 'Configuración pública aplicada a %s.\n' "${REPOSITORY}"
printf 'GitHub Pages: %s\n' "${PAGES_URL}"
printf 'Disparando despliegue de Pages...\n'
gh workflow run pages.yml --repo "${REPOSITORY}" --ref main

printf '\nWiki habilitada. Para sincronizar su contenido versionado ejecuta:\n'
printf '  bash scripts/publish-wiki.sh --apply\n'
