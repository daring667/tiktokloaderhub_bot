import contextlib
import os


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
