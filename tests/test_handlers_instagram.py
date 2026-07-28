"""Tests for handlers/instagram.py: the Telegram-facing Instagram Reels flow."""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from handlers.instagram import register
from _helpers import FakeApp, make_message, make_client

URL = "https://www.instagram.com/reel/ABC123/"


def _register():
    app = FakeApp()
    db = MagicMock()
    register(app, db)
    return app.message_handlers[0], db


class TestInstagramHandler:
    @pytest.mark.asyncio
    async def test_no_url_replies_error(self):
        handler, db = _register()
        message = make_message("no link here")
        client = make_client()

        await handler(client, message)

        assert "Не найдена ссылка Instagram" in message.reply.await_args.args[0]
        client.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_download_sends_video_and_logs(self, tmp_path):
        handler, db = _register()
        message = make_message(URL)
        client = make_client()
        fake_video = tmp_path / "vid.mp4"

        with patch("handlers.instagram.InstagramDownloader") as MockDownloader:
            instance = MockDownloader.return_value
            instance.title = "Cool Reel"

            async def fake_download(filename):
                fake_video.write_bytes(b"fake")
                return str(fake_video)
            instance.download = AsyncMock(side_effect=fake_download)

            await handler(client, message)

        client.send_video.assert_awaited_once()
        db.log_download.assert_called_once_with(message.from_user.id, "instagram", URL)
        status_msg = message.reply.return_value
        status_msg.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_oversized_file_rejected_after_download(self, tmp_path):
        handler, db = _register()
        message = make_message(URL)
        client = make_client()
        fake_video = tmp_path / "big.mp4"
        fake_video.write_bytes(b"x")

        with patch("handlers.instagram.InstagramDownloader") as MockDownloader, \
             patch("handlers.instagram.os.path.getsize", return_value=60 * 1024 * 1024):
            instance = MockDownloader.return_value
            instance.title = "Big Reel"
            instance.download = AsyncMock(return_value=str(fake_video))

            await handler(client, message)

        client.send_video.assert_not_called()
        db.log_download.assert_not_called()
        status_msg = message.reply.return_value
        assert "больше 50" in status_msg.edit_text.await_args.args[0]

    @pytest.mark.asyncio
    async def test_send_failure_does_not_log_analytics(self, tmp_path):
        handler, db = _register()
        message = make_message(URL)
        client = make_client()
        client.send_video = AsyncMock(side_effect=Exception("network blip"))
        fake_video = tmp_path / "vid.mp4"
        fake_video.write_bytes(b"fake")

        with patch("handlers.instagram.InstagramDownloader") as MockDownloader:
            instance = MockDownloader.return_value
            instance.title = "Cool Reel"
            instance.download = AsyncMock(return_value=str(fake_video))

            await handler(client, message)

        db.log_download.assert_not_called()
        status_msg = message.reply.return_value
        assert "Ошибка при отправке" in status_msg.edit_text.await_args.args[0]

    @pytest.mark.asyncio
    async def test_value_error_from_downloader_shown_to_user(self):
        handler, db = _register()
        message = make_message(URL)
        client = make_client()

        with patch("handlers.instagram.InstagramDownloader") as MockDownloader:
            MockDownloader.side_effect = ValueError("yt-dlp не смог распарсить Instagram-ссылку.")
            await handler(client, message)

        assert "не смог распарсить" in message.reply.await_args.args[0]
        db.log_download.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_download_for_same_user_is_rejected(self):
        handler, db = _register()
        message1 = make_message(URL, user_id=71)
        message2 = make_message(URL, user_id=71)
        client = make_client()

        started = asyncio.Event()
        release = asyncio.Event()

        with patch("handlers.instagram.InstagramDownloader") as MockDownloader:
            instance = MockDownloader.return_value
            instance.title = "Reel"

            async def slow_download(filename):
                started.set()
                await release.wait()
                return filename
            instance.download = AsyncMock(side_effect=slow_download)

            task = asyncio.create_task(handler(client, message1))
            await started.wait()

            await handler(client, message2)

            release.set()
            await task

        assert "уже идет другая загрузка" in message2.reply.await_args.args[0]
