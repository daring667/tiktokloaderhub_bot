"""Tests for services/utils/progress_bar.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from services.utils.progress_bar import progress, humanbytes


def _message():
    message = MagicMock()
    message.edit_text = AsyncMock()
    return message


class TestProgressGuards:
    """The function must never raise on degenerate inputs — it's called from
    a yt-dlp progress hook, where sizes are often unknown."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current,total", [
        (100, 0),      # size unknown — used to be ZeroDivisionError
        (100, None),
        (0, 1000),     # nothing downloaded yet
        (0, 0),
    ])
    async def test_degenerate_input_is_ignored(self, current, total):
        message = _message()
        await progress(current, total, message, start=0, filename="x")
        message.edit_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_normal_progress_is_rendered(self):
        import time
        message = _message()
        await progress(500, 1000, message, start=time.time() - 10, filename="x")

        message.edit_text.assert_awaited_once()
        text = message.edit_text.await_args.kwargs["text"]
        assert "50.0%" in text
        assert "ETA" in text


class TestHumanBytes:
    def test_zero_is_blank(self):
        assert humanbytes(0) == ""

    def test_kilobytes(self):
        assert "KB" in humanbytes(2048)

    def test_megabytes(self):
        assert "MB" in humanbytes(5 * 1024 * 1024)
