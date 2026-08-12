import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "config" / "render_route.py"
TEMPLATE = ROOT / "config" / "save-sync.yml.template"
API_ONLY_TEMPLATE = ROOT / "config" / "save-sync-api-only.yml.template"


def write_env(path, game_key="example-game"):
    path.write_text(
        "\n".join(
            [
                f"SAVE_SYNC_GAME_KEY={game_key}",
                "SAVE_SYNC_HOST_STORAGE_PATH=/srv/save-sync/example-game",
                "SAVE_SYNC_PUBLIC_ROOT=/var/www/html",
                "SAVE_SYNC_PUBLIC_HOST=sync.example.com",
                "SAVE_SYNC_PROXY_SECRET=" + "a" * 64,
                "SAVE_SYNC_CSRF_SECRET=" + "b" * 64,
                "SAVE_SYNC_AUTHENTIK_FORWARD_AUTH_URL=http://auth-proxy:9000/check",
                "SAVE_SYNC_TRAEFIK_CERT_RESOLVER=letsencrypt",
            ]
        ),
        encoding="utf-8",
    )


def write_game(path, game_key="example-game"):
    path.write_text(json.dumps({"key": game_key}), encoding="utf-8")


def test_route_renderer_is_atomic_private_and_game_scoped(tmp_path):
    env_path = tmp_path / ".env"
    game_path = tmp_path / "game.json"
    output = tmp_path / "runtime" / "route.yml"
    write_env(env_path)
    write_game(game_path)

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--env",
            str(env_path),
            "--template",
            str(TEMPLATE),
            "--output",
            str(output),
            "--game",
            str(game_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = output.read_text(encoding="utf-8")
    assert "__SAVE_SYNC_" not in rendered
    assert "/api/games/example-game" in rendered
    assert "save-sync-example-game" in rendered
    assert "certResolver: letsencrypt" in rendered
    assert oct(os.stat(output).st_mode & 0o777) == "0o600"


def test_route_renderer_rejects_game_key_mismatch(tmp_path):
    env_path = tmp_path / ".env"
    game_path = tmp_path / "game.json"
    write_env(env_path, "example-game")
    write_game(game_path, "other-game")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--env",
            str(env_path),
            "--template",
            str(TEMPLATE),
            "--output",
            str(tmp_path / "route.yml"),
            "--game",
            str(game_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


def test_api_only_route_has_no_panel_or_forward_auth(tmp_path):
    env_path = tmp_path / ".env"
    game_path = tmp_path / "game.json"
    output = tmp_path / "route.yml"
    write_env(env_path)
    write_game(game_path)

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--env",
            str(env_path),
            "--template",
            str(API_ONLY_TEMPLATE),
            "--output",
            str(output),
            "--game",
            str(game_path),
        ],
        check=True,
    )
    rendered = output.read_text(encoding="utf-8")
    assert "/api/games/example-game" in rendered
    assert "Path(`/games/example-game`)" not in rendered
    assert "forwardAuth" not in rendered
    assert "__SAVE_SYNC_" not in rendered
