"""Tests for handlers/tiktok.py: the Telegram-facing TikTok flow."""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from handlers.tiktok import TikTokHandler
from _helpers import FakeApp, make_message, make_client

URL = "https://www.tiktok.com/@user/video/123"


def _register():
    app = FakeApp()
    db = MagicMock()
    TikTokHandler(app, db).register()
    return app.message_handlers[0], db


class TestTikTokHandler:
    @pytest.mark.asyncio
    async def test_no_url_replies_error(self):
        handler, db = _register()
        message = make_message("just some text, no link")
        client = make_client()

        await handler(client, message)

        message.reply.assert_awaited_once()
        assert "Не найдена ссылка" in message.reply.await_args.args[0]
        client.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_download_sends_video_and_logs(self, tmp_path):
        handler, db = _register()
        message = make_message(URL)
        client = make_client()
        fake_video = tmp_path / "video.mp4"

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            async def fake_download(filename):
                fake_video.write_bytes(b"fake")
                return str(fake_video)
            MockDownloader.return_value.download = AsyncMock(side_effect=fake_download)

            await handler(client, message)

        client.send_video.assert_awaited_once()
        assert client.send_video.await_args.kwargs["video"] == str(fake_video)
        db.register_user.assert_called_once_with(message.from_user.id, message.from_user.username, message.from_user.first_name)
        db.log_download.assert_called_once_with(message.from_user.id, "tiktok", URL)
        message.delete.assert_awaited_once()
        assert not fake_video.exists()  # temp file cleaned up

    @pytest.mark.asyncio
    async def test_value_error_shown_to_user_and_not_logged(self):
        handler, db = _register()
        message = make_message(URL)
        client = make_client()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            MockDownloader.return_value.download = AsyncMock(
                side_effect=ValueError("Видео слишком большое (более 50 МБ).")
            )
            await handler(client, message)

        status_msg = message.reply.return_value
        status_msg.edit.assert_awaited_once()
        assert "слишком большое" in status_msg.edit.await_args.args[0]
        db.log_download.assert_not_called()
        client.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_unexpected_error_shows_generic_message(self):
        handler, db = _register()
        message = make_message(URL)
        client = make_client()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            MockDownloader.return_value.download = AsyncMock(side_effect=RuntimeError("boom"))
            await handler(client, message)

        status_msg = message.reply.return_value
        assert "Ошибка при скачивании видео" in status_msg.edit.await_args.args[0]
        db.log_download.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_download_for_same_user_is_rejected(self):
        handler, db = _register()
        message1 = make_message(URL, user_id=7)
        message2 = make_message(URL, user_id=7)
        client = make_client()

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_download(filename):
            started.set()
            await release.wait()
            return filename

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            MockDownloader.return_value.download = AsyncMock(side_effect=slow_download)

            task = asyncio.create_task(handler(client, message1))
            await started.wait()

            await handler(client, message2)  # fired while message1's download is still running

            release.set()
            await task

        message2.reply.assert_awaited_once()
        assert "идёт другая загрузка" in message2.reply.await_args.args[0]

    @pytest.mark.asyncio
    async def test_different_users_download_concurrently(self):
        handler, db = _register()
        message1 = make_message(URL, user_id=7)
        message2 = make_message(URL, user_id=8)
        client = make_client()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            async def fake_download(filename):
                return filename
            MockDownloader.return_value.download = AsyncMock(side_effect=fake_download)

            await asyncio.gather(handler(client, message1), handler(client, message2))

        assert client.send_video.await_count == 2
