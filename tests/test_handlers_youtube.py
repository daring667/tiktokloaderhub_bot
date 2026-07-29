"""Tests for handlers/youtube.py: the Telegram-facing YouTube flow."""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from pyrogram.enums import ParseMode

from handlers.youtube import register, format_duration
from _helpers import FakeApp, make_message, make_client, make_callback

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _register(db=None):
    app = FakeApp()
    db = db if db is not None else MagicMock()
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
        args, kwargs = message.reply.await_args
        markup = kwargs["reply_markup"]
        assert len(markup.inline_keyboard) == 3  # 2 quality options + cancel
        assert "🎬 720p" in markup.inline_keyboard[0][0].text
        assert "🎬 360p" in markup.inline_keyboard[1][0].text
        assert markup.inline_keyboard[2][0].callback_data == "yt|cancel"
        assert kwargs["parse_mode"] == ParseMode.HTML
        client.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_quality_buttons_put_audio_after_video_regardless_of_size(self):
        """A small audio track shouldn't jump above bigger video options."""
        handler, _cb, db = _register()
        message = make_message(URL)
        client = make_client()

        streams = [
            {"itag": "bestaudio", "res": "audio (mp3)", "filesize": 50 * 1024 * 1024, "type": "audio"},
            {"itag": "18", "res": "360p", "filesize": 10 * 1024 * 1024, "type": "video"},
        ]

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            MockYT.return_value = _make_meta(length=300, streams=streams)
            await handler(client, message)

        _, kwargs = message.reply.await_args
        markup = kwargs["reply_markup"]
        assert "🎬 360p" in markup.inline_keyboard[0][0].text
        assert "🎵" in markup.inline_keyboard[1][0].text

    @pytest.mark.asyncio
    async def test_title_with_markdown_special_chars_is_escaped_not_broken(self):
        """Regression test: an unescaped title with markdown-ish characters
        used to break Telegram's Markdown parser and show literal asterisks
        instead of bold text. HTML + escaping avoids that entirely."""
        handler, _cb, db = _register()
        message = make_message(URL)
        client = make_client()

        streams = [
            {"itag": "22", "res": "720p", "filesize": 40 * 1024 * 1024, "type": "video"},
            {"itag": "18", "res": "360p", "filesize": 10 * 1024 * 1024, "type": "video"},
        ]

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            MockYT.return_value = _make_meta(length=300, streams=streams, title="Look <ma> *no* hands & fun_stuff")
            await handler(client, message)

        args, kwargs = message.reply.await_args
        assert "<ma>" not in args[0]
        assert "&lt;ma&gt;" in args[0]
        assert kwargs["parse_mode"] == ParseMode.HTML

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

    @pytest.mark.asyncio
    async def test_multiple_links_in_one_message_all_downloaded(self):
        handler, _cb, db = _register()
        url2 = "https://www.youtube.com/watch?v=abcdefghijk"
        message = make_message(f"{URL} {url2}")
        client = make_client()

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            meta = _make_meta(length=30)

            async def fake_download(itag, filename, msg, status_msg):
                open(filename, "wb").close()
                return filename
            meta.download = AsyncMock(side_effect=fake_download)
            MockYT.return_value = meta

            await handler(client, message)

        assert client.send_video.await_count == 2
        assert db.log_download.call_count == 2
        message.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_source_message_kept_if_every_link_fails(self):
        handler, _cb, db = _register()
        url2 = "https://www.youtube.com/watch?v=abcdefghijk"
        message = make_message(f"{URL} {url2}")
        client = make_client()

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            MockYT.side_effect = ValueError("boom")
            await handler(client, message)

        message.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_rapid_second_request_is_rate_limited(self, tmp_path):
        handler, _cb, db = _register()
        message1 = make_message(URL, user_id=55)
        message2 = make_message(URL, user_id=55)
        client = make_client()

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            meta = _make_meta(length=30)
            fake_video = tmp_path / "v.mp4"

            async def fake_download(itag, filename, msg, status_msg):
                fake_video.write_bytes(b"x")
                return str(fake_video)
            meta.download = AsyncMock(side_effect=fake_download)
            MockYT.return_value = meta

            await handler(client, message1)
            await handler(client, message2)

        assert client.send_video.await_count == 1
        assert "Подожди ещё" in message2.reply.await_args.args[0]


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

    @pytest.mark.asyncio
    async def test_successful_download_deletes_quality_picker_message(self, tmp_path):
        _msg, callback_handler, db = _register()
        callback = make_callback("yt|18|dQw4w9WgXcQ")
        client = make_client()
        fake_video = tmp_path / "v.mp4"

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            meta = _make_meta(length=30, streams=[{"itag": "18", "res": "360p", "filesize": 1000, "type": "video"}])

            async def fake_download(itag, filename, msg, status_msg):
                fake_video.write_bytes(b"x")
                return str(fake_video)
            meta.download = AsyncMock(side_effect=fake_download)
            MockYT.return_value = meta

            await callback_handler(client, callback)

        callback.message.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_button_dismisses_quality_picker(self):
        _msg, callback_handler, db = _register()
        callback = make_callback("yt|cancel")

        await callback_handler(None, callback)

        callback.message.delete.assert_awaited_once()
        callback.answer.assert_awaited_once()


class TestYoutubePlaylist:
    PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLxyz"

    @staticmethod
    def _video_urls(n=3):
        return [f"https://youtube.com/watch?v=v{i}" for i in range(n)]

    @staticmethod
    async def _mock_download(tmp_path, meta, name="v.mp4"):
        fake_video = tmp_path / name

        async def fake_download(itag, filename, msg, status_msg):
            fake_video.write_bytes(b"x")
            return str(fake_video)
        meta.download = AsyncMock(side_effect=fake_download)

    @pytest.mark.asyncio
    async def test_playlist_link_downloads_first_and_offers_next(self, tmp_db, tmp_path):
        handler, _cb, db = _register(tmp_db)
        message = make_message(self.PLAYLIST_URL)
        client = make_client()
        video_urls = self._video_urls(3)

        with patch("handlers.youtube.get_playlist_info", return_value=("My Playlist", video_urls, 3)), \
             patch("handlers.youtube.YouTubeDownloader") as MockYT:
            meta = _make_meta(length=30)
            await self._mock_download(tmp_path, meta)
            MockYT.return_value = meta

            await handler(client, message)

        assert client.send_video.await_count == 1

        last_call = message.reply.await_args_list[-1]
        assert "Скачать следующее" in last_call.args[0]
        markup = last_call.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert any(cd.startswith("yt|plnext|") for cd in callback_datas)
        assert any(cd.startswith("yt|plstop|") for cd in callback_datas)

    @pytest.mark.asyncio
    async def test_playlist_keeps_the_source_message(self, tmp_db, tmp_path):
        """Unlike a single video, a playlist link must survive: the
        step-through prompts reply to it and the user may want it back."""
        handler, _cb, db = _register(tmp_db)
        message = make_message(self.PLAYLIST_URL)
        client = make_client()
        video_urls = self._video_urls(3)

        with patch("handlers.youtube.get_playlist_info", return_value=("My Playlist", video_urls, 3)), \
             patch("handlers.youtube.YouTubeDownloader") as MockYT:
            meta = _make_meta(length=30)
            await self._mock_download(tmp_path, meta)
            MockYT.return_value = meta

            await handler(client, message)

        message.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_playlist_with_no_videos_shows_error(self, tmp_db):
        handler, _cb, db = _register(tmp_db)
        message = make_message(self.PLAYLIST_URL)
        client = make_client()

        with patch("handlers.youtube.get_playlist_info", side_effect=ValueError("Плейлист пуст или недоступен.")):
            await handler(client, message)

        assert "пуст" in message.reply.await_args.args[0]
        client.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_plnext_downloads_next_video_and_offers_another(self, tmp_db, tmp_path):
        _msg, callback_handler, db = _register(tmp_db)
        video_urls = self._video_urls(3)
        db.save_playlist_state("tok1", video_urls, 3)

        callback = make_callback("yt|plnext|tok1")
        client = make_client()

        with patch("handlers.youtube.YouTubeDownloader") as MockYT:
            meta = _make_meta(length=30)
            await self._mock_download(tmp_path, meta)
            MockYT.return_value = meta

            await callback_handler(client, callback)

        assert client.send_video.await_count == 1
        callback.message.delete.assert_awaited_once()  # old "next?" prompt removed
        # one reply for the download status, one more offering video 3
        assert callback.message.reply.await_count == 2
        assert db.get_playlist_state("tok1")["index_pos"] == 1

    @pytest.mark.asyncio
    async def test_plnext_on_last_video_ends_playlist(self, tmp_db):
        _msg, callback_handler, db = _register(tmp_db)
        video_urls = self._video_urls(2)
        db.save_playlist_state("tok1", video_urls, 2)
        db.advance_playlist_state("tok1")  # now on the last video (index 1)

        callback = make_callback("yt|plnext|tok1")
        client = make_client()

        await callback_handler(client, callback)

        assert db.get_playlist_state("tok1") is None
        callback.message.edit_text.assert_awaited_once()
        assert "закончился" in callback.message.edit_text.await_args.args[0]

    @pytest.mark.asyncio
    async def test_plstop_deletes_state_and_message(self, tmp_db):
        _msg, callback_handler, db = _register(tmp_db)
        db.save_playlist_state("tok1", self._video_urls(3), 3)

        callback = make_callback("yt|plstop|tok1")
        await callback_handler(None, callback)

        assert db.get_playlist_state("tok1") is None
        callback.message.delete.assert_awaited_once()
        callback.answer.assert_awaited_once()


class TestFormatDuration:
    def test_seconds_only(self):
        assert format_duration(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert format_duration(229) == "3:49"

    def test_hours(self):
        assert format_duration(3725) == "1:02:05"

    def test_zero_or_none(self):
        assert format_duration(0) == "0:00"
        assert format_duration(None) == "0:00"
