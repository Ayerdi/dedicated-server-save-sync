FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

LABEL org.opencontainers.image.source="https://github.com/Ayerdi/dedicated-server-save-sync" \
      org.opencontainers.image.description="Concurrency-safe save synchronization for dedicated game servers" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --system --uid 10001 --create-home savesync
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# Official binary pinned by version and SHA-256. Both deployment
# architectures are supported; any unexpected asset makes
# the build fail instead of silently accepting another restic version.
ARG RESTIC_VERSION=0.18.0
ARG TARGETARCH
RUN RESTIC_VERSION="${RESTIC_VERSION}" TARGETARCH="${TARGETARCH}" python - <<'PY'
import bz2
import hashlib
import os
import pathlib
import platform
import urllib.request

version = os.environ["RESTIC_VERSION"]
raw_arch = (os.environ.get("TARGETARCH") or platform.machine()).lower()
arch_aliases = {
    "amd64": "amd64",
    "x86_64": "amd64",
    "arm64": "arm64",
    "aarch64": "arm64",
}
try:
    arch = arch_aliases[raw_arch]
except KeyError as exc:
    raise SystemExit(f"Arquitectura restic no soportada: {raw_arch}") from exc
checksums = {
    "amd64": "98f6dd8bf5b59058d04bfd8dab58e196cc2a680666ccee90275a3b722374438e",
    "arm64": "ce18179c25dc5f2e33e3c233ba1e580f9de1a4566d2977e8d9600210363ec209",
}
expected = checksums[arch]
name = f"restic_{version}_linux_{arch}.bz2"
url = f"https://github.com/restic/restic/releases/download/v{version}/{name}"
request = urllib.request.Request(
    url, headers={"User-Agent": "dedicated-server-save-sync-build"}
)
with urllib.request.urlopen(request, timeout=60) as response:
    compressed = response.read()
actual = hashlib.sha256(compressed).hexdigest()
if actual != expected:
    raise SystemExit(f"Invalid restic SHA-256: {actual} != {expected}")
target = pathlib.Path("/usr/local/bin/restic")
target.write_bytes(bz2.decompress(compressed))
target.chmod(0o755)
PY
RUN RESTIC_VERSION="${RESTIC_VERSION}" python -c "import os,subprocess; out=subprocess.check_output(['restic','version'],text=True).split(); assert out[1] == os.environ['RESTIC_VERSION'], out"

COPY save_sync ./save_sync
COPY wsgi.py ./
RUN mkdir -p /data/save-sync/backups /data/save-sync/temporary \
    && chown -R savesync:savesync /data/save-sync \
    && chmod 700 /data/save-sync/temporary
USER savesync
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
STOPSIGNAL SIGTERM
CMD ["gunicorn", "--bind=0.0.0.0:8080", "--workers=2", "--threads=4", "--timeout=900", "--access-logfile=-", "--error-logfile=-", "wsgi:app"]