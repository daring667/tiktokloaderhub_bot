import asyncio
import contextlib
import html
import logging
import math
import os
import time
import traceback

from pyrogram.enums import ParseMode

from services.utils.env import resolve_admin_id
from services.user_settings import reacts_in_groups


def ignores_links_in_groups(db, message) -> bool:
    """True when this user asked the bot to leave their group links alone.

    Private chats are never affected -- the switch is about not answering for
    someone in a shared chat, not about turning the bot off. A database hiccup
    must not silence the bot either, so anything unexpected means "react".
    """
    try:
        chat = getattr(message, "chat", None)
        user = getattr(message, "from_user", None)
        if not db or not user or not chat:
            return False
        if getattr(chat.type, "name", "") == "PRIVATE" or chat.type == "private":
            return False
        return not reacts_in_groups(db.get_user_settings(user.id))
    except Exception:
        return False

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


class RateLimited(Exception):
    """Raised when the user is making requests faster than REQUEST_COOLDOWN_SECONDS apart."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"rate limited, retry after {retry_after:.1f}s")


# Minimum gap between the end of one request and the start of the next, per
# user — this catches rapid-fire back-to-back spam that download_slot alone
# doesn't (it only blocks truly *overlapping* requests). Reset on restart.
REQUEST_COOLDOWN_SECONDS = float(os.getenv("REQUEST_COOLDOWN_SECONDS", "5"))
_last_finished_at: dict = {}  # key -> monotonic timestamp

# Cap on downloads running at once *across all users*. The per-user lock alone
# doesn't bound this: N users means N concurrent yt-dlp/ffmpeg processes, which
# a small box can't take. Extra requests queue up instead of piling on.
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
_download_semaphore: "asyncio.Semaphore | None" = None


def get_download_semaphore() -> asyncio.Semaphore:
    """Created lazily so it binds to the loop the bot actually runs on."""
    global _download_semaphore
    if _download_semaphore is None:
        _download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    return _download_semaphore


@contextlib.asynccontextmanager
async def download_slot(active_downloads: set, key, enforce_cooldown: bool = True):
    """Reserves `key` in `active_downloads` for the duration of the block.

    Raises DownloadInProgress if a download for this key is already running,
    or RateLimited if the previous one for this key finished too recently.
    Callers decide how to reply to the user in either case.

    `enforce_cooldown=False` skips only the rate limit, not the lock — for
    explicit button presses inside an already-started session (e.g. "next
    video" in a playlist), where the user is *meant* to click immediately
    after the previous download and a cooldown would just be in the way.
    """
    if key in active_downloads:
        raise DownloadInProgress()

    if enforce_cooldown:
        last = _last_finished_at.get(key)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < REQUEST_COOLDOWN_SECONDS:
                raise RateLimited(REQUEST_COOLDOWN_SECONDS - elapsed)

    active_downloads.add(key)
    try:
        # Hold the user's slot while queueing, so their own follow-up
        # requests still bounce off DownloadInProgress rather than stacking.
        async with get_download_semaphore():
            yield
    finally:
        active_downloads.discard(key)
        _last_finished_at[key] = time.monotonic()


def rate_limit_message(exc: "RateLimited") -> str:
    """Consistent wording for the RateLimited reply across all handlers."""
    return f"⏳ Подожди ещё {math.ceil(exc.retry_after)} сек. перед следующей ссылкой."


def user_key_for(message):
    """Stable per-user (or per-chat, for anonymous senders) lock key."""
    return message.from_user.id if message.from_user else f"chat:{message.chat.id}"


MAX_LINKS_PER_MESSAGE = 5


def extract_platform_urls(text: str, is_platform_url) -> tuple[list, int]:
    """All URLs in `text` matching `is_platform_url`, capped at
    MAX_LINKS_PER_MESSAGE so one message can't queue up an unbounded batch.

    Returns (urls_to_process, total_matching_found) — the second value lets
    the caller tell the user when some links were dropped by the cap.
    """
    from services.downloader import extract_urls
    matches = [u for u in extract_urls(text or "") if is_platform_url(u)]
    return matches[:MAX_LINKS_PER_MESSAGE], len(matches)


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


# Offering support once per failure would mean five identical offers for a
# message carrying five bad links.
SUPPORT_OFFER_COOLDOWN = 120
_support_offer_state: dict = {}


async def offer_support(client, message, user, db) -> None:
    """Attach a way to reach a human to a failure the user just saw.

    Private chats only: in a group this would be noise for everyone else,
    and the reporter can still use /report in the bot's own chat.
    """
    from handlers.support import report_button
    try:
        chat = getattr(message, 'chat', None)
        if message is None or user is None or chat is None:
            return
        if getattr(chat.type, 'name', '') != 'PRIVATE':
            return
        now = time.monotonic()
        last = _support_offer_state.get(user.id)
        if last is not None and (now - last) < SUPPORT_OFFER_COOLDOWN:
            return
        _support_offer_state[user.id] = now
        await message.reply(
            'Если это повторяется — расскажи, что случилось, и я разберусь.',
            reply_markup=report_button(),
        )
    except Exception as e:
        logging.warning('could not offer support: %s', e)


async def report_error(client, platform: str, url: str, user, exc: Exception,
                       db=None, message=None):
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
        # Remembered for every failure, not just the ones that alert the
        # admin: a report filed later should still quote the right link.
        if user is not None:
            with contextlib.suppress(Exception):
                db.remember_failure(user.id, platform, url, type(exc).__name__)

    # Before the admin-alert throttle below: the person in front of the error
    # needs the button every time, however many alerts were suppressed.
    if message is not None:
        await offer_support(client, message, user, db)

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
