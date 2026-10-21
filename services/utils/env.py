import os


def resolve_admin_id() -> int:
    """Telegram user ID allowed to run /stats.

    ADMIN_ID takes priority; OWNER_ID is used as a fallback only when
    ADMIN_ID is unset or empty — an empty string does not count as "set".
    """
    return int(os.getenv("ADMIN_ID") or os.getenv("OWNER_ID") or "0")


MINIAPP_URL_DEFAULT = (
    "https://daring667.github.io/tiktokloaderhub_bot/downloader.html"
    "?api=https://debian-2.tail4f778c.ts.net&v=20260821-4"
)


def get_miniapp_url() -> str:
    """Where the downloader Mini App is served from.

    Read in one place: both the menu button and the /app command open it, and
    a cache-busting version lives in the query string, so two copies of this
    string drift apart the first time it is bumped.
    """
    return os.getenv("MINIAPP_URL") or MINIAPP_URL_DEFAULT
