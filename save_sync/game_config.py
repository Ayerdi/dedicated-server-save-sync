import json
import re
from dataclasses import dataclass
from pathlib import Path

GAME_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

DEFAULT_GAME = {
    "key": "palworld",
    "displayName": "Palworld",
    "identityField": "worldGuid",
    "identityLabel": "World GUID",
    "identityPattern": r"^[A-F0-9]{32}$",
    "identityNormalization": "uppercase",
    "identityKind": "string",
    "legacyPalworldRoutes": True,
    "managedHosts": False,
}


@dataclass(frozen=True)
class GameConfiguration:
    raw: dict
    key: str
    display_name: str
    identity_field: str
    identity_label: str
    normalization: str
    identity_kind: str
    identity_re: re.Pattern
    legacy_palworld: bool
    managed_hosts: bool

    def normalize_identity_value(self, value):
        raw = str(value or "").strip()
        if self.normalization == "uppercase":
            raw = raw.upper()
        elif self.normalization == "lowercase":
            raw = raw.lower()
        if self.identity_kind == "int64":
            try:
                parsed = int(raw)
            except ValueError:
                return None
            if not -(2**63) <= parsed <= (2**63) - 1 or raw != str(parsed):
                return None
        if not raw or len(raw) > 256 or not self.identity_re.fullmatch(raw):
            return None
        return raw

    def extension_payload(self):
        return {
            **self.raw,
            "key": self.key,
            "displayName": self.display_name,
            "identityField": self.identity_field,
            "identityLabel": self.identity_label,
        }


def load_game_configuration(app_config):
    game = dict(DEFAULT_GAME)
    game_config_path = str(app_config.get("SAVE_SYNC_GAME_CONFIG_PATH", "")).strip()
    if game_config_path:
        try:
            loaded_game = json.loads(Path(game_config_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Could not load the game configuration") from exc
        if not isinstance(loaded_game, dict):
            raise RuntimeError("The game configuration must be a JSON object")
        game.update(loaded_game)

    game_key = str(game.get("key", "")).strip().lower()
    expected_game_key = str(app_config["SAVE_SYNC_GAME_KEY"]).strip().lower()
    display_game = str(game.get("displayName", "")).strip()
    identity_field = str(game.get("identityField", "")).strip()
    identity_label = str(game.get("identityLabel", "")).strip()
    normalization = str(game.get("identityNormalization", "none")).strip().lower()
    identity_kind = str(game.get("identityKind", "string")).strip().lower()

    if not GAME_KEY_RE.fullmatch(game_key):
        raise RuntimeError("game.key must use lowercase letters, numbers and hyphens")
    if expected_game_key != game_key:
        raise RuntimeError("SAVE_SYNC_GAME_KEY does not match game.key")
    if not display_game or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", identity_field):
        raise RuntimeError("displayName or identityField are invalid")
    if not identity_label or normalization not in {"none", "uppercase", "lowercase"}:
        raise RuntimeError("identityLabel or identityNormalization are invalid")
    if identity_kind not in {"string", "int64"}:
        raise RuntimeError("identityKind must be string or int64")
    try:
        identity_re = re.compile(str(game.get("identityPattern", "")))
    except re.error as exc:
        raise RuntimeError("identityPattern is not a valid regular expression") from exc
    if not game.get("identityPattern"):
        raise RuntimeError("identityPattern is required")

    return GameConfiguration(
        raw=game,
        key=game_key,
        display_name=display_game,
        identity_field=identity_field,
        identity_label=identity_label,
        normalization=normalization,
        identity_kind=identity_kind,
        identity_re=identity_re,
        legacy_palworld=bool(game.get("legacyPalworldRoutes", False)),
        managed_hosts=bool(game.get("managedHosts", False)),
    )
