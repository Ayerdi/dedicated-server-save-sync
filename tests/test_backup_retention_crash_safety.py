import sqlite3

from save_sync import create_app
from save_sync.backup_supervisor import BackupSupervisor

WORLD_GUID = "A7E97BAA767DB9029EF013BB71E993A0"


class SuccessfulProcess:
    pid = 999999

    def wait(self, timeout=None):
        return 0


def test_reconcile_failure_after_commit_leaves_only_recoverable_orphan(
    tmp_path, monkeypatch
):
    storage = tmp_path / "storage"
    db_path = storage / "save-sync.sqlite3"
    app = create_app(
        {
            "TESTING": True,
            "SAVE_SYNC_STORAGE_PATH": str(storage),
            "SAVE_SYNC_DB_PATH": str(db_path),
            "SAVE_SYNC_REQUIRE_HTTPS": False,
            "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
            "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
            "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
            "SAVE_SYNC_RETENTION_PER_SLOT": 1,
        }
    )
    old_path = storage / "backups/save-v000001.zip"
    current_path = storage / "backups/save-v000002.zip"
    old_path.write_bytes(b"old")
    current_path.write_bytes(b"current")

    with app.extensions["save_sync_connect"]() as db:
        user_id = db.execute(
            "SELECT id FROM users WHERE username='admin'"
        ).fetchone()[0]
        for version, path in ((1, old_path), (2, current_path)):
            db.execute(
                "INSERT INTO versions(version,path,sha256,size,updated_by,updated_at,base_version,save_identity) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    version,
                    f"backups/{path.name}",
                    "0" * 64,
                    path.stat().st_size,
                    user_id,
                    f"2026-01-01T00:00:0{version}Z",
                    version - 1,
                    WORLD_GUID,
                ),
            )
        db.execute("INSERT INTO current_save(singleton,version) VALUES(1,2)")
        db.execute(
            "INSERT INTO pending_backups(version,started_at) VALUES(1,?)",
            ("2026-01-01T00:00:01Z",),
        )

    supervisor = BackupSupervisor(
        storage_path=storage,
        db_path=db_path,
        command="true",
        timeout_seconds=30,
        poll_seconds=0.01,
        retention_per_slot=1,
        identities={"admin": {"displayName": "Host A", "slot": "host-a"}},
        popen=lambda *args, **kwargs: SuccessfulProcess(),
    )

    original_reconcile = supervisor.reconcile_filesystem

    def fail_reconcile():
        raise sqlite3.OperationalError("fallo físico inyectado")

    monkeypatch.setattr(supervisor, "reconcile_filesystem", fail_reconcile)
    assert supervisor.run_once() is True

    # El COMMIT de resultado/retención ya ocurrió antes de intentar unlink: el
    # fallo físico no puede restaurar una fila que apunte al ZIP que se iba a
    # borrar. Queda únicamente un fichero huérfano, que es el estado seguro.
    with app.extensions["save_sync_connect"]() as db:
        versions = [
            row[0] for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]
        pending = db.execute("SELECT count(*) FROM pending_backups").fetchone()[0]
        completed = db.execute(
            "SELECT count(*) FROM audit WHERE event='backup_hook_completed' AND success=1"
        ).fetchone()[0]
    assert versions == [2]
    assert pending == 0
    assert completed == 1
    assert old_path.is_file()
    assert current_path.is_file()

    monkeypatch.setattr(supervisor, "reconcile_filesystem", original_reconcile)
    supervisor.reconcile_filesystem()
    assert not old_path.exists()
    assert current_path.is_file()
