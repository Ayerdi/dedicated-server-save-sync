import hashlib

import pytest

from save_sync import create_app


def app_config(tmp_path, **overrides):
    config = {
        "TESTING": True,
        "SAVE_SYNC_STORAGE_PATH": str(tmp_path / "storage"),
        "SAVE_SYNC_DB_PATH": str(tmp_path / "storage" / "db.sqlite3"),
        "SAVE_SYNC_REQUIRE_HTTPS": False,
        "SAVE_SYNC_PROXY_SECRET": "proxy-test-secret",
        "SAVE_SYNC_CSRF_SECRET": "csrf-test-secret",
        "SAVE_SYNC_WEB_USERS": "operator:admin",
        "SAVE_SYNC_USER_IDENTITIES_JSON": (
            '{"operator":{"displayName":"Example Host","slot":"host-one"}}'
        ),
    }
    config.update(overrides)
    return config


def test_custom_identity_controls_owner_and_display(tmp_path):
    app = create_app(app_config(tmp_path))
    token = "pws_example_test"
    with app.extensions["save_sync_connect"]() as db:
        user_id = db.execute(
            "SELECT id FROM users WHERE username='operator'"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO api_tokens(user_id,name,token_hash,created_at) "
            "VALUES(?,?,?,datetime('now'))",
            (user_id, "test", hashlib.sha256(token.encode()).hexdigest()),
        )

    response = app.test_client().post(
        "/api/games/palworld/lock",
        headers={"Authorization": f"Bearer {token}"},
        json={"owner": "Example Host", "clientId": "example-pc"},
    )
    assert response.status_code == 201


@pytest.mark.parametrize(
    "identities",
    ["not-json", "[]", '{"operator":{"displayName":"","slot":"one"}}'],
)
def test_invalid_identity_configuration_fails_closed(tmp_path, identities):
    with pytest.raises(RuntimeError):
        create_app(
            app_config(tmp_path, SAVE_SYNC_USER_IDENTITIES_JSON=identities)
        )
