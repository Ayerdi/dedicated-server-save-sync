#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_UID="$(id -u)"
REPO_GID="$(id -g)"
PYTHON_IMAGE="python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"

docker run --rm \
  -e REPO_UID="${REPO_UID}" -e REPO_GID="${REPO_GID}" \
  -v "${ROOT_DIR}:/repo" -w /repo "${PYTHON_IMAGE}" sh -ec '
    python -m pip install --quiet pip-tools==7.6.0
    pip-compile --generate-hashes --strip-extras --output-file=requirements.txt requirements.in
    pip-compile --allow-unsafe --generate-hashes --strip-extras --output-file=requirements-dev.txt requirements-dev.in
    chown "$REPO_UID:$REPO_GID" requirements.txt requirements-dev.txt
  '

docker run --rm -v "${ROOT_DIR}:/repo:ro" -w /repo "${PYTHON_IMAGE}" sh -ec '
  python -m pip install --quiet --require-hashes -r requirements-dev.txt
  pip-audit -r requirements.txt --progress-spinner=off
'

printf 'Locks regenerados y auditados. Revisa el diff antes de confirmar cambios.\n'
