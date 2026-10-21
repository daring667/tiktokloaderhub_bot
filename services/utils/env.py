import os


def resolve_admin_id() -> int:
    """Telegram user ID allowed to run /stats.

    ADMIN_ID takes priority; OWNER_ID is used as a fallback only when
    ADMIN_ID is unset or empty — an empty string does not count as "set".
    """
    return int(os.getenv("ADMIN_ID") or os.getenv("OWNER_ID") or "0")
