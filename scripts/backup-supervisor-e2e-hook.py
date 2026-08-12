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

# v1 waits for a signal so the E2E can kill/restart the web container
# while backup continues under the independent sidecar.
if version == 1:
    release = temporary / "backup-e2e-release-v1"
    while not release.exists():
        time.sleep(0.1)

# v2 deliberately blocks the first attempt. The test kills the
# supervisor with SIGKILL; after restart the durable queue must trigger attempt 2.
elif version == 2 and attempt == 1:
    while True:
        time.sleep(1)
