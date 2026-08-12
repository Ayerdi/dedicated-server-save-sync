import os
import time
from pathlib import Path

storage = Path(os.environ.get("SAVE_SYNC_STORAGE_PATH", "/data/save-sync"))
temporary = storage / "temporary"
temporary.mkdir(parents=True, exist_ok=True)
version = int(os.environ["SAVE_SYNC_PUBLISHED_VERSION"])
counter = temporary / f"backup-e2e-attempt-v{version}"
try:
    attempt = int(counter.read_text(encoding="utf-8")) + 1
except (OSError, ValueError):
    attempt = 1
counter.write_text(str(attempt), encoding="utf-8")
(temporary / f"backup-e2e-started-v{version}-{attempt}").touch()

# v1 espera una señal para que el E2E pueda matar/reiniciar el contenedor web
# mientras el backup continúa bajo el sidecar independiente.
if version == 1:
    release = temporary / "backup-e2e-release-v1"
    while not release.exists():
        time.sleep(0.1)

# v2 bloquea deliberadamente el primer intento. El test mata el propio
# supervisor con SIGKILL; al reiniciarse, la cola durable debe provocar intento 2.
elif version == 2 and attempt == 1:
    while True:
        time.sleep(1)
