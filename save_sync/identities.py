import json


def load_identities(raw):
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("SAVE_SYNC_USER_IDENTITIES_JSON is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(  # noqa: TRY004
            "SAVE_SYNC_USER_IDENTITIES_JSON must be a JSON object"
        )

    result = {}
    for username, profile in value.items():
        if not isinstance(profile, dict):
            raise RuntimeError(  # noqa: TRY004
                f"Invalid identity profile for {username}"
            )
        display = str(profile.get("displayName", "")).strip()
        slot = str(profile.get("slot", "")).strip()
        if not str(username).strip() or not display or not slot:
            raise RuntimeError(
                "Each identity requires non-empty username, displayName and slot values"
            )
        result[str(username).casefold()] = {"displayName": display, "slot": slot}
    return result


def identity_for_username(identities, username):
    return identities.get(
        username.casefold(),
        {"displayName": username, "slot": username.casefold()},
    )
