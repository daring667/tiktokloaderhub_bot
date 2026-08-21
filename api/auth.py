"""Telegram Mini App initData validation."""

import hashlib
import hmac
import time
from urllib.parse import parse_qsl


class TelegramAuthError(ValueError):
    """Raised when Telegram Web App authentication data is invalid."""


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict:
    if not init_data or not bot_token:
        raise TelegramAuthError("Telegram authentication is required")

    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise TelegramAuthError("Telegram authentication hash is missing")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items())
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(received_hash, expected_hash):
        raise TelegramAuthError("Telegram authentication is invalid")

    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TelegramAuthError("Telegram authentication timestamp is invalid") from exc

    if max_age >= 0 and time.time() - auth_date > max_age:
        raise TelegramAuthError("Telegram authentication has expired")
    if auth_date - time.time() > 60:
        raise TelegramAuthError("Telegram authentication timestamp is invalid")

    return fields


def user_id_from_init_data(fields: dict) -> int:
    import json

    try:
        user = json.loads(fields["user"])
        return int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegramAuthError("Telegram user identity is invalid") from exc
