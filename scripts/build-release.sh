#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-}"
[[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  printf 'Usage: %s MAJOR.MINOR.PATCH\n' "$0" >&2
  exit 2
}
[[ -f "${ROOT_DIR}/LICENSE" ]] || { printf 'LICENSE is missing.\n' >&2; exit 1; }

DIST_DIR="${ROOT_DIR}/dist"
ARCHIVE="${DIST_DIR}/dedicated-server-save-sync-client-v${VERSION}.zip"
CHECKSUM="${ARCHIVE}.sha256"
mkdir -p "${DIST_DIR}"

python3 - "${ROOT_DIR}" "${ARCHIVE}" "${VERSION}" <<'PY'
import pathlib
import stat
import sys
import zipfile

root = pathlib.Path(sys.argv[1])
archive_path = pathlib.Path(sys.argv[2])
version = sys.argv[3]
prefix = f"dedicated-server-save-sync-client-v{version}"
files = [
    *(
        path
        for path in (root / "client").rglob("*")
        if path.is_file()
        and "tests" not in path.relative_to(root / "client").parts
        and path.name not in {"config.json", "secrets.json"}
        and "data" not in path.relative_to(root / "client").parts
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
printf '%s\n%s\n' "${ARCHIVE}" "${CHECKSUM}"
