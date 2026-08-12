#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="8.24.3"

case "$(uname -m)" in
  x86_64|amd64)
    ARCHIVE_ARCH="x64"
    EXPECTED_SHA256="9991e0b2903da4c8f6122b5c3186448b927a5da4deef1fe45271c3793f4ee29c"
    ;;
  aarch64|arm64)
    ARCHIVE_ARCH="arm64"
    EXPECTED_SHA256="5f2edbe1f49f7b920f9e06e90759947d3c5dfc16f752fb93aaafc17e9d14cf07"
    ;;
  *)
    printf 'Unsupported architecture for this checker: %s\n' "$(uname -m)" >&2
    exit 2
    ;;
esac

TEMP_DIR="$(mktemp -d /tmp/save-sync-gitleaks.XXXXXX)"
trap 'rm -rf -- "${TEMP_DIR}"' EXIT
ARCHIVE="${TEMP_DIR}/gitleaks.tar.gz"

curl --fail --silent --show-error --location \
  --output "${ARCHIVE}" \
  "https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/gitleaks_${VERSION}_linux_${ARCHIVE_ARCH}.tar.gz"
printf '%s  %s\n' "${EXPECTED_SHA256}" "${ARCHIVE}" | sha256sum --check --status
tar --extract --gzip --file "${ARCHIVE}" --directory "${TEMP_DIR}" gitleaks
"${TEMP_DIR}/gitleaks" detect --source "${ROOT_DIR}" --redact --no-banner
