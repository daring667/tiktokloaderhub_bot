"""Tests for handlers/youtube.py: the Telegram-facing YouTube flow."""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from handlers.youtube import register
from _helpers import FakeApp, make_message, make_client, make_callback

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _register():
    app = FakeApp()
    db = MagicMock()
    register(app, db)
    return app.message_handlers[0], app.callback_handlers[0], db


def _make_meta(length=30, streams=None, title="Test Video"):
    meta = MagicMock()
    meta.length = length
    meta.streams = streams if streams is not None else [
        {"itag": "18", "res": "360p", "filesize": 1000, "type": "video"}
    ]
    meta.title = title
    meta.url = URL
    return meta


class TestYoutubeMessageHandler:
    @pytest.mark.asyncio
    async def test_no_url_replies_error(self):
        handler, _cb, db = _register()
        message = make_message("no link here")
        client = make_client()

        await handler(client, message)

        assert "Не смог найти ссылку" in message.reply.await_args.args[0]
        client.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_short_single_stream_downloads_directly(self, tmp_path):
        handler, _cb, db = _register()
        message = make_message(URL)
        client = make_client()
        fake_video = tmp_path / "v.mp4"

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            meta = _make_meta(length=30)
            MockYT.return_value = meta

            async def fake_download(itag, filename, msg, status_msg):
                fake_video.write_bytes(b"fake")
                return str(fake_video)
            meta.download = AsyncMock(side_effect=fake_download)

            await handler(client, message)

        client.send_video.assert_awaited_once()
        db.log_download.assert_called_once_with(message.from_user.id, "youtube", URL)
        assert not fake_video.exists()

    @pytest.mark.asyncio
    async def test_long_video_multiple_streams_offers_quality_buttons(self):
        handler, _cb, db = _register()
        message = make_message(URL)
        client = make_client()

        streams = [
            {"itag": "22", "res": "720p", "filesize": 40 * 1024 * 1024, "type": "video"},
            {"itag": "18", "res": "360p", "filesize": 10 * 1024 * 1024, "type": "video"},
        ]

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            MockYT.return_value = _make_meta(length=300, streams=streams)
            await handler(client, message)

        message.reply.assert_awaited_once()
        _, kwargs = message.reply.await_args
        markup = kwargs["reply_markup"]
        assert len(markup.inline_keyboard) == 2
        client.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_oversized_file_rejected_after_download(self, tmp_path):
        handler, _cb, db = _register()
        message = make_message(URL)
        client = make_client()
        fake_video = tmp_path / "big.mp4"
        fake_video.write_bytes(b"x")

        with patch("handlers.youtube.YouTubeDownloader") as MockYT, \
             patch("handlers.youtube.os.path.getsize", return_value=60 * 1024 * 1024):
            meta = _make_meta(length=30)
            meta.download = AsyncMock(return_value=str(fake_video))
            MockYT.return_value = meta

            await handler(client, message)

        client.send_video.assert_not_called()
        db.log_download.assert_not_called()
        status_msg = message.reply.return_value
        assert "больше 50" in status_msg.edit_text.await_args.args[0]

    @pytest.mark.asyncio
    async def test_send_failure_does_not_log_and_keeps_error_visible(self, tmp_path):
        """Regression test: a failed send used to still log analytics and
        immediately delete the status message that showed the error."""
        handler, _cb, db = _register()
        message = make_message(URL)
        client = make_client()
        client.send_video = AsyncMock(side_effect=Exception("network blip"))
        fake_video = tmp_path / "v.mp4"
        fake_video.write_bytes(b"fake")

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            meta = _make_meta(length=30)
            meta.download = AsyncMock(return_value=str(fake_video))
            MockYT.return_value = meta

            await handler(client, message)

        db.log_download.assert_not_called()
        status_msg = message.reply.return_value
        status_msg.edit_text.assert_awaited_once()
        assert "Ошибка при отправке файла" in status_msg.edit_text.await_args.args[0]
        status_msg.delete.assert_not_awaited()  # error must stay visible

    @pytest.mark.asyncio
    async def test_reports_error_to_admin_on_parse_failure(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ID", "999")
        handler, _cb, db = _register()
        message = make_message(URL)
        client = make_client()
        client.send_message = AsyncMock()

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            MockYT.side_effect = ValueError("yt-dlp broke")
            await handler(client, message)

        client.send_message.assert_awaited_once()
        args, _ = client.send_message.await_args
        assert args[0] == 999
        assert "yt-dlp broke" in args[1]

    @pytest.mark.asyncio
    async def test_concurrent_download_for_same_user_is_rejected(self):
        handler, _cb, db = _register()
        message1 = make_message(URL, user_id=71)
        message2 = make_message(URL, user_id=71)
        client = make_client()

        started = asyncio.Event()
        release = asyncio.Event()

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            meta = _make_meta(length=30)

            async def slow_download(itag, filename, msg, status_msg):
                started.set()
                await release.wait()
                return filename
            meta.download = AsyncMock(side_effect=slow_download)
            MockYT.return_value = meta

            task = asyncio.create_task(handler(client, message1))
            await started.wait()

            await handler(client, message2)

            release.set()
            await task

        assert "идёт другая загрузка" in message2.reply.await_args.args[0]


class TestYoutubeCallbackHandler:
    @pytest.mark.asyncio
    async def test_invalid_callback_format_shows_alert(self):
        _msg, callback_handler, db = _register()
        callback = make_callback("yt")  # only one part, not 2 or 3

        await callback_handler(None, callback)

        callback.answer.assert_awaited_once()
        args, kwargs = callback.answer.await_args
        assert "Неверный формат" in args[0]
        assert kwargs.get("show_alert") is True

    @pytest.mark.asyncio
    async def test_expired_token_shows_alert(self):
        _msg, callback_handler, db = _register()
        db.get_callback.return_value = None
        callback = make_callback("yt|deadbeef")

        await callback_handler(None, callback)

        args, kwargs = callback.answer.await_args
        assert "истёк" in args[0] or "недействительна" in args[0]
        assert kwargs.get("show_alert") is True
