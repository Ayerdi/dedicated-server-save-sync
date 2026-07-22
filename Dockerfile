FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --system --uid 10001 --create-home savesync
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY save_sync ./save_sync
COPY wsgi.py ./
RUN mkdir -p /data/save-sync/backups /data/save-sync/temporary && chown -R savesync:savesync /data/save-sync
USER savesync
EXPOSE 8080
CMD ["gunicorn", "--bind=0.0.0.0:8080", "--workers=2", "--threads=4", "--timeout=900", "--access-logfile=-", "--error-logfile=-", "wsgi:app"]
