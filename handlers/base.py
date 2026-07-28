import contextlib
import html
import os
import time
import traceback

from pyrogram.enums import ParseMode

from services.utils.env import resolve_admin_id

# How often the same (platform, exception type) combo may alert the admin.
# Reset on process restart — that's fine, a restart is a natural reset point.
ERROR_REPORT_COOLDOWN = int(os.getenv("ERROR_REPORT_COOLDOWN_SECONDS", "300"))
_error_alert_state: dict = {}  # (platform, exc_type_name) -> {"last_sent": t, "suppressed": n}


class BaseHandler:
    def __init__(self, app):
        self.app = app

    def register(self):
        raise NotImplementedError("Реализуй метод register() в подклассе")


class DownloadInProgress(Exception):
    """Raised when the user already has a download running on this platform."""


@contextlib.asynccontextmanager
async def download_slot(active_downloads: set, key):
    """Reserves `key` in `active_downloads` for the duration of the block.

    Raises DownloadInProgress instead of silently proceeding, so callers
    decide how to reply to the user.
    """
    if key in active_downloads:
        raise DownloadInProgress()
    active_downloads.add(key)
    try:
        yield
    finally:
        active_downloads.discard(key)


def user_key_for(message):
    """Stable per-user (or per-chat, for anonymous senders) lock key."""
    return message.from_user.id if message.from_user else f"chat:{message.chat.id}"


async def safe_delete(message):
    """Best-effort message deletion — never raises."""
    if message is None:
        return
    with contextlib.suppress(Exception):
        await message.delete()


def cleanup_files(*paths):
    """Best-effort removal of temp files — never raises."""
    for path in paths:
        if path and os.path.exists(path):
            with contextlib.suppress(Exception):
                os.remove(path)


async def report_error(client, platform: str, url: str, user, exc: Exception, db=None):
    """Records a failed download and, best-effort, alerts ADMIN_ID/OWNER_ID.

    Always logged to `db` (if given) for /stats error-rate reporting. The
    Telegram alert itself is throttled per (platform, exception type) so a
    burst of identical failures doesn't flood the admin's chat — the next
    alert that does go through reports how many were suppressed meanwhile.

    Never raises — a broken notification must not break the user-facing flow.
    """
    if db is not None:
        with contextlib.suppress(Exception):
            db.log_error(platform, type(exc).__name__, str(exc))

    admin_id = resolve_admin_id()
    if not admin_id:
        return

    key = (platform, type(exc).__name__)
    now = time.monotonic()
    state = _error_alert_state.get(key)

    if state is not None and (now - state["last_sent"]) < ERROR_REPORT_COOLDOWN:
        state["suppressed"] += 1
        return

    suppressed = state["suppressed"] if state is not None else 0
    _error_alert_state[key] = {"last_sent": now, "suppressed": 0}

    if user is not None and getattr(user, "username", None):
        user_desc = f"@{user.username}"
    elif user is not None:
        user_desc = str(user.id)
    else:
        user_desc = "unknown"

    tb = traceback.format_exc()
    if tb.strip() == "NoneType: None":
        tb = ""  # report_error called outside an except block
    if len(tb) > 2000:
        tb = tb[-2000:]

    text = (
        f"⚠️ Ошибка загрузки — {html.escape(platform)}\n"
        f"Пользователь: {html.escape(user_desc)}\n"
        f"Ссылка: {html.escape(url or '—')}\n\n"
        f"<b>{html.escape(type(exc).__name__)}</b>: {html.escape(str(exc))}"
    )
    if tb:
        text += f"\n\n<pre>{html.escape(tb)}</pre>"
    if suppressed:
        cooldown_min = ERROR_REPORT_COOLDOWN // 60
        text += f"\n\n<i>(+{suppressed} похожих ошибок подавлено за последние {cooldown_min} мин.)</i>"

    with contextlib.suppress(Exception):
        await client.send_message(admin_id, text, parse_mode=ParseMode.HTML)
