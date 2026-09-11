#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-}"
INCLUDE_EXPERIMENTAL_VALHEIM="${SAVE_SYNC_INCLUDE_EXPERIMENTAL_VALHEIM:-0}"
[[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  printf 'Usage: %s MAJOR.MINOR.PATCH\n' "$0" >&2
  exit 2
}
[[ -f "${ROOT_DIR}/LICENSE" ]] || { printf 'LICENSE is missing.\n' >&2; exit 1; }

DIST_DIR="${ROOT_DIR}/dist"
ARCHIVE="${DIST_DIR}/dedicated-server-save-sync-client-v${VERSION}.zip"
CHECKSUM="${ARCHIVE}.sha256"
mkdir -p "${DIST_DIR}"

[[ "${INCLUDE_EXPERIMENTAL_VALHEIM}" =~ ^[01]$ ]] || {
  printf 'SAVE_SYNC_INCLUDE_EXPERIMENTAL_VALHEIM must be 0 or 1.\n' >&2
  exit 2
}

python3 - "${ROOT_DIR}" "${ARCHIVE}" "${VERSION}" "${INCLUDE_EXPERIMENTAL_VALHEIM}" <<'PY'
import pathlib
import stat
import sys
import zipfile

root = pathlib.Path(sys.argv[1])
archive_path = pathlib.Path(sys.argv[2])
version = sys.argv[3]
include_experimental_valheim = sys.argv[4] == "1"
prefix = f"dedicated-server-save-sync-client-v{version}"
experimental_valheim_files = {
    pathlib.PurePosixPath("Start-ValheimSync.cmd"),
    pathlib.PurePosixPath("Iniciar-ValheimSync.cmd"),
    pathlib.PurePosixPath("config.valheim.example.json"),
    pathlib.PurePosixPath("MANUAL-ACCEPTANCE-VALHEIM.md"),
}

def include_client_file(path):
    relative = path.relative_to(root / "client")
    if "tests" in relative.parts or path.name in {"config.json", "secrets.json"} or "data" in relative.parts:
        return False
    if include_experimental_valheim:
        return True
    if relative.parts[:2] == ("adapters", "valheim"):
        return False
    return pathlib.PurePosixPath(relative.as_posix()) not in experimental_valheim_files

files = [
    *(
        path
        for path in (root / "client").rglob("*")
        if path.is_file()
        and include_client_file(path)
    ),
    root / "CHANGELOG.md",
    root / "LICENSE",
    root / "SECURITY.md",
]

with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
    for path in sorted(files, key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root)
        info = zipfile.ZipInfo(f"{prefix}/{relative.as_posix()}")
        info.date_time = (1980, 1, 1, 0, 0, 0)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
PY

archive_name="$(basename -- "${ARCHIVE}")"
(cd "${DIST_DIR}" && sha256sum "${archive_name}") >"${CHECKSUM}"
if [[ "${INCLUDE_EXPERIMENTAL_VALHEIM}" == "1" ]]; then
  printf 'WARNING: experimental Valheim client files were included by explicit request.\n' >&2
fi
printf '%s\n%s\n' "${ARCHIVE}" "${CHECKSUM}"
