#!/usr/bin/env python3
import argparse
import json
import os
import pathlib
import re
import tempfile


def read_env(path):
    values = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if not match:
            raise ValueError(f"Invalid line in .env: {number}")
        key, value = match.groups()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def render(env_path, template_path, output_path, game_path):
    values = read_env(env_path)
    for key in ("SAVE_SYNC_PROXY_SECRET", "SAVE_SYNC_CSRF_SECRET"):
        value = values.get(key, "")
        if len(value) < 32 or value.startswith("REPLACE"):
            raise ValueError(f"{key} must contain at least 32 random characters")

    storage = pathlib.Path(values.get("SAVE_SYNC_HOST_STORAGE_PATH", ""))
    if not storage.is_absolute():
        raise ValueError("SAVE_SYNC_HOST_STORAGE_PATH must be an absolute path")
    public_root = pathlib.Path(
        values.get("SAVE_SYNC_PUBLIC_ROOT", "/var/www/html")
    ).resolve()
    resolved_storage = storage.resolve()
    if resolved_storage == public_root or public_root in resolved_storage.parents:
        raise ValueError("Storage cannot be inside the public directory")

    game = json.loads(game_path.read_text(encoding="utf-8"))
    game_key = values.get("SAVE_SYNC_GAME_KEY", "")
    if game.get("key") != game_key:
        raise ValueError("SAVE_SYNC_GAME_KEY does not match the game JSON")

    template = template_path.read_text(encoding="utf-8")
    replacements = {
        '"__SAVE_SYNC_PROXY_SECRET__"': values["SAVE_SYNC_PROXY_SECRET"],
        '"__SAVE_SYNC_AUTHENTIK_FORWARD_AUTH_URL__"': values.get(
            "SAVE_SYNC_AUTHENTIK_FORWARD_AUTH_URL", ""
        ),
    }
    for marker, value in replacements.items():
        count = template.count(marker)
        if count == 0:
            continue
        if count != 1 or not value:
            raise ValueError(f"Invalid deployment marker or value: {marker}")
        template = template.replace(marker, json.dumps(value))

    host = values.get("SAVE_SYNC_PUBLIC_HOST", "")
    host_marker = "__SAVE_SYNC_PUBLIC_HOST__"
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or template.count(host_marker) < 1:
        raise ValueError("SAVE_SYNC_PUBLIC_HOST or its markers are invalid")
    template = template.replace(host_marker, host)

    cert_resolver = values.get("SAVE_SYNC_TRAEFIK_CERT_RESOLVER", "")
    cert_marker = "__SAVE_SYNC_CERT_RESOLVER__"
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+", cert_resolver)
        or template.count(cert_marker) < 1
    ):
        raise ValueError("SAVE_SYNC_TRAEFIK_CERT_RESOLVER is invalid")
    template = template.replace(cert_marker, cert_resolver)

    game_marker = "__SAVE_SYNC_GAME_KEY__"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", game_key):
        raise ValueError("SAVE_SYNC_GAME_KEY is invalid")
    if game_marker not in template:
        raise ValueError("Missing SAVE_SYNC_GAME_KEY marker")
    rendered = template.replace(game_marker, game_key)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", dir=output_path.parent
    )
    temporary = pathlib.Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
        directory_fd = os.open(output_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=pathlib.Path, required=True)
    parser.add_argument("--template", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--game", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        render(args.env, args.template, args.output, args.game)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
