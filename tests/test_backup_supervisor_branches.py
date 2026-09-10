import signal
import sqlite3
import subprocess

import pytest

from save_sync import create_app
from save_sync.app import SCHEMA_VERSION
from save_sync.backup_supervisor import BackupSupervisor, healthcheck

WORLD_GUID = "A7E97BAA767DB9029EF013BB71E993A0"


def make_app(tmp_path):
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
        }
    )
    return app, storage, db_path


def queue_one(app, storage):
    relative = "backups/save-v000001.zip"
    (storage / relative).write_bytes(b"v1")
    with app.extensions["save_sync_connect"]() as db:
        user_id = db.execute(
            "SELECT id FROM users WHERE username='admin'"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO versions(version,path,sha256,size,updated_by,updated_at,base_version,save_identity) "
            "VALUES(1,?,?,?,?,?,?,?)",
            (
                relative,
                "0" * 64,
                2,
                user_id,
                "2026-01-01T00:00:00Z",
                0,
                WORLD_GUID,
            ),
        )
        db.execute("INSERT INTO current_save(singleton,version) VALUES(1,1)")
        db.execute(
            "INSERT INTO pending_backups(version,started_at) VALUES(1,?)",
            ("2026-01-01T00:00:00Z",),
        )


def supervisor(storage, db_path):
    return BackupSupervisor(
        storage_path=storage,
        db_path=db_path,
        command="true",
        timeout_seconds=30,
        poll_seconds=0.01,
        retention_per_slot=1,
        identities={"admin": {"displayName": "Host A", "slot": "host-a"}},
    )


def test_schema_ready_rejects_missing_and_future_database(tmp_path):
    storage = tmp_path / "missing"
    storage.mkdir()
    db_path = storage / "save-sync.sqlite3"
    worker = supervisor(storage, db_path)

    assert worker.schema_ready() is False
    assert not db_path.exists()

    app, storage, db_path = make_app(tmp_path / "initialized")
    worker = supervisor(storage, db_path)
    assert worker.schema_ready() is True
    with app.extensions["save_sync_connect"]() as db:
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    assert worker.schema_ready() is False


def test_mark_attempt_started_detects_job_removed_between_poll_and_claim(tmp_path):
    app, storage, db_path = make_app(tmp_path)
    queue_one(app, storage)
    worker = supervisor(storage, db_path)
    job = worker.next_job()
    with app.extensions["save_sync_connect"]() as db:
        db.execute("DELETE FROM pending_backups WHERE version=1")

    assert worker.mark_attempt_started(job) is False


def test_mark_attempt_started_rolls_back_if_audit_fails(tmp_path, monkeypatch):
    app, storage, db_path = make_app(tmp_path)
    queue_one(app, storage)
    worker = supervisor(storage, db_path)
    job = worker.next_job()

    def fail_audit(*_args, **_kwargs):
        raise sqlite3.OperationalError("audit failure")

    monkeypatch.setattr(worker, "audit", fail_audit)
    with pytest.raises(sqlite3.OperationalError):
        worker.mark_attempt_started(job)

    with app.extensions["save_sync_connect"]() as db:
        started_at = db.execute(
            "SELECT started_at FROM pending_backups WHERE version=1"
        ).fetchone()[0]
    assert started_at == "2026-01-01T00:00:00Z"


def test_reconcile_filesystem_rolls_back_helper_failure(tmp_path, monkeypatch):
    _, storage, db_path = make_app(tmp_path)
    worker = supervisor(storage, db_path)

    def fail_reconcile(*_args, **_kwargs):
        raise sqlite3.OperationalError("reconcile failure")

    monkeypatch.setattr(
        "save_sync.backup_supervisor.reconcile_unreferenced_files_locked",
        fail_reconcile,
    )
    with pytest.raises(sqlite3.OperationalError):
        worker.reconcile_filesystem()


def test_terminate_process_group_returns_if_group_already_gone(tmp_path, monkeypatch):
    _, storage, db_path = make_app(tmp_path)
    worker = supervisor(storage, db_path)
    calls = []

    class Process:
        pid = 123

    def killpg(pgid, sig):
        calls.append((pgid, sig))
        raise ProcessLookupError

    monkeypatch.setattr("save_sync.backup_supervisor.os.killpg", killpg)
    worker.terminate_process_group(Process())
    assert calls == [(123, signal.SIGTERM)]


def test_terminate_process_group_stops_when_group_dies_after_sigterm(
    tmp_path, monkeypatch
):
    _, storage, db_path = make_app(tmp_path)
    worker = supervisor(storage, db_path)
    calls = []

    class Process:
        pid = 123

        def wait(self, timeout=None):
            assert timeout == 2
            return 0

    def killpg(pgid, sig):
        calls.append((pgid, sig))
        if sig == 0:
            raise ProcessLookupError

    monkeypatch.setattr("save_sync.backup_supervisor.os.killpg", killpg)
    worker.terminate_process_group(Process(), sigterm_timeout=2)
    assert calls == [(123, signal.SIGTERM), (123, 0)]


def test_terminate_process_group_kills_grandchild_after_leader_exits(
    tmp_path, monkeypatch
):
    _, storage, db_path = make_app(tmp_path)
    worker = supervisor(storage, db_path)
    calls = []
    waits = []

    class Process:
        pid = 123

        def wait(self, timeout=None):
            waits.append(timeout)
            return 0

    monkeypatch.setattr(
        "save_sync.backup_supervisor.os.killpg",
        lambda pgid, sig: calls.append((pgid, sig)),
    )
    worker.terminate_process_group(Process(), sigterm_timeout=2, sigkill_timeout=3)
    assert calls == [
        (123, signal.SIGTERM),
        (123, 0),
        (123, signal.SIGKILL),
    ]
    assert waits == [2, 3]


def test_terminate_process_group_escalates_and_tolerates_stuck_child(
    tmp_path, monkeypatch
):
    _, storage, db_path = make_app(tmp_path)
    worker = supervisor(storage, db_path)
    calls = []

    class Process:
        pid = 123

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd=["restic"], timeout=timeout or 0)

    monkeypatch.setattr(
        "save_sync.backup_supervisor.os.killpg",
        lambda pgid, sig: calls.append((pgid, sig)),
    )
    worker.terminate_process_group(
        Process(), sigterm_timeout=0.01, sigkill_timeout=0.01
    )
    assert calls == [
        (123, signal.SIGTERM),
        (123, 0),
        (123, signal.SIGKILL),
    ]


def test_healthcheck_rejects_pending_queue_without_command(tmp_path, monkeypatch):
    app, storage, db_path = make_app(tmp_path)
    queue_one(app, storage)
    worker = supervisor(storage, db_path)
    worker.touch_heartbeat()

    monkeypatch.setenv("SAVE_SYNC_STORAGE_PATH", str(storage))
    monkeypatch.setenv("SAVE_SYNC_DB_PATH", str(db_path))
    monkeypatch.setenv("SAVE_SYNC_POST_PUBLISH_COMMAND", "")
    monkeypatch.setenv("SAVE_SYNC_BACKUP_POLL_SECONDS", "0.01")
    assert healthcheck() is False

    with app.extensions["save_sync_connect"]() as db:
        db.execute("DELETE FROM pending_backups")
    assert healthcheck() is True


def test_run_once_warns_only_once_when_pending_backup_is_disabled(
    tmp_path, monkeypatch
):
    app, storage, db_path = make_app(tmp_path)
    queue_one(app, storage)
    worker = supervisor(storage, db_path)
    worker.command = ""
    warnings = []
    monkeypatch.setattr(
        worker.logger,
        "warning",
        lambda *args, **_kwargs: warnings.append(args),
    )

    assert worker.run_once() is False
    assert worker.run_once() is False
    assert len(warnings) == 1


def test_run_once_does_not_launch_after_losing_claim(tmp_path, monkeypatch):
    app, storage, db_path = make_app(tmp_path)
    queue_one(app, storage)
    worker = supervisor(storage, db_path)
    launched = []
    monkeypatch.setattr(worker, "mark_attempt_started", lambda _job: False)
    monkeypatch.setattr(worker, "popen", lambda *a, **k: launched.append((a, k)))

    assert worker.run_once() is True
    assert launched == []


def test_run_forever_survives_startup_reconcile_and_iteration_failure(
    tmp_path, monkeypatch
):
    _, storage, db_path = make_app(tmp_path)
    worker = supervisor(storage, db_path)
    events = []
    schema = iter([False, True, True])

    monkeypatch.setattr(worker, "acquire_singleton_lock", lambda: events.append("lock"))
    monkeypatch.setattr(worker, "release_singleton_lock", lambda: events.append("unlock"))
    monkeypatch.setattr(worker, "schema_ready", lambda: next(schema, True))
    monkeypatch.setattr(
        worker,
        "reconcile_filesystem",
        lambda: (_ for _ in ()).throw(sqlite3.OperationalError("startup reconcile")),
    )

    def run_once():
        worker.stop_requested = True
        raise sqlite3.OperationalError("iteration failure")

    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr(worker, "touch_heartbeat", lambda: events.append("heartbeat"))
    monkeypatch.setattr(worker, "sleep", lambda _seconds: events.append("sleep"))

    worker.run_forever()
    assert events[0] == "lock"
    assert "sleep" in events
    assert "heartbeat" in events
    assert events[-1] == "unlock"
