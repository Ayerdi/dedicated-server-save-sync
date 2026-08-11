FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

LABEL org.opencontainers.image.source="https://github.com/Ayerdi/dedicated-server-save-sync" \
      org.opencontainers.image.description="Concurrency-safe save synchronization for dedicated game servers" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --system --uid 10001 --create-home savesync
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
RUN apt-get update \
 && apt-get install -y --no-install-recommends restic \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*
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
