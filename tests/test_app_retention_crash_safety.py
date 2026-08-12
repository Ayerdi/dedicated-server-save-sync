import sqlite3

import save_sync.app as app_module

WORLD_GUID = "A7E97BAA767DB9029EF013BB71E993A0"


def app_config(storage, retention):
    return {
        "TESTING": True,
        "SAVE_SYNC_STORAGE_PATH": str(storage),
        "SAVE_SYNC_DB_PATH": str(storage / "save-sync.sqlite3"),
        "SAVE_SYNC_REQUIRE_HTTPS": False,
        "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
        "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
        "SAVE_SYNC_RATE_LIMIT_PER_MINUTE": 10000,
        "SAVE_SYNC_RETENTION_PER_SLOT": retention,
    }


def seed_two_versions(app, storage):
    paths = []
    with app.extensions["save_sync_connect"]() as db:
        user_id = db.execute(
            "SELECT id FROM users WHERE username='admin'"
        ).fetchone()[0]
        for version in (1, 2):
            relative = f"backups/save-v{version:06d}.zip"
            path = storage / relative
            path.write_bytes(f"v{version}".encode())
            paths.append(path)
            db.execute(
                "INSERT INTO versions(version,path,sha256,size,updated_by,updated_at,base_version,save_identity) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    version,
                    relative,
                    "0" * 64,
                    2,
                    user_id,
                    f"2026-01-0{version}T00:00:00Z",
                    version - 1,
                    WORLD_GUID,
                ),
            )
        db.execute("INSERT INTO current_save(singleton,version) VALUES(1,2)")
    return paths


def read_versions(db_path):
    with sqlite3.connect(db_path) as db:
        return [
            row[0] for row in db.execute("SELECT version FROM versions ORDER BY version")
        ]


def test_backend_retention_commits_metadata_before_filesystem_reconciliation(
    tmp_path, monkeypatch
):
    storage = tmp_path / "storage"
    first = app_module.create_app(app_config(storage, retention=2))
    old_path, current_path = seed_two_versions(first, storage)
    db_path = storage / "save-sync.sqlite3"

    with monkeypatch.context() as patch:
        patch.setattr(
            app_module,
            "reconcile_unreferenced_files_locked",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("simulated crash after metadata commit")
            ),
        )
        # Physical reconciliation is best-effort: a failure after COMMIT
        # must not roll back metadata or prevent backend startup.
        app_module.create_app(app_config(storage, retention=1))

    assert read_versions(db_path) == [2]
    assert old_path.is_file()
    assert current_path.is_file()

    # A later startup revalidates references and removes the orphan ZIP.
    app_module.create_app(app_config(storage, retention=1))
    assert read_versions(db_path) == [2]
    assert not old_path.exists()
    assert current_path.is_file()
