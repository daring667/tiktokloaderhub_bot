import contextlib
import html
import os
import traceback

from pyrogram.enums import ParseMode

from services.utils.env import resolve_admin_id


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


async def report_error(client, platform: str, url: str, user, exc: Exception):
    """Best-effort notification to ADMIN_ID/OWNER_ID about a failed download.

    Never raises — a broken notification must not break the user-facing flow.
    """
    admin_id = resolve_admin_id()
    if not admin_id:
        return

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

    with contextlib.suppress(Exception):
        await client.send_message(admin_id, text, parse_mode=ParseMode.HTML)
