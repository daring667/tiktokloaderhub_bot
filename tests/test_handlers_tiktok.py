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
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {}})
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
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {}})
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
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {}})
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
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {}})
            MockDownloader.return_value.download = AsyncMock(side_effect=slow_download)

            task = asyncio.create_task(handler(client, message1))
            await started.wait()

            await handler(client, message2)  # fired while message1's download is still running

            release.set()
            await task

        message2.reply.assert_awaited_once()
        assert "идёт другая загрузка" in message2.reply.await_args.args[0]

    @pytest.mark.asyncio
    async def test_reports_error_to_admin_on_failure(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ID", "999")
        handler, db = _register()
        message = make_message(URL)
        client = make_client()
        client.send_message = AsyncMock()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {}})
            MockDownloader.return_value.download = AsyncMock(side_effect=ValueError("API broken"))
            await handler(client, message)

        client.send_message.assert_awaited_once()
        args, _ = client.send_message.await_args
        assert args[0] == 999
        assert "API broken" in args[1]

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
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {}})
            MockDownloader.return_value.download = AsyncMock(side_effect=fake_download)

            await asyncio.gather(handler(client, message1), handler(client, message2))

        assert client.send_video.await_count == 2

    @pytest.mark.asyncio
    async def test_multiple_links_in_one_message_all_downloaded(self):
        handler, db = _register()
        url2 = "https://www.tiktok.com/@user/video/456"
        message = make_message(f"{URL} {url2}")
        client = make_client()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            async def fake_download(filename):
                open(filename, "wb").close()
                return filename
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {}})
            MockDownloader.return_value.download = AsyncMock(side_effect=fake_download)

            await handler(client, message)

        assert client.send_video.await_count == 2
        assert db.log_download.call_count == 2
        message.delete.assert_awaited_once()  # original message deleted once, after the whole batch

    @pytest.mark.asyncio
    async def test_source_message_kept_if_every_link_fails(self):
        handler, db = _register()
        url2 = "https://www.tiktok.com/@user/video/456"
        message = make_message(f"{URL} {url2}")
        client = make_client()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {}})
            MockDownloader.return_value.download = AsyncMock(side_effect=ValueError("boom"))
            await handler(client, message)

        message.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_too_many_links_are_capped_with_a_warning(self):
        from handlers.base import MAX_LINKS_PER_MESSAGE
        handler, db = _register()
        urls_text = " ".join(f"https://www.tiktok.com/@u/video/{i}" for i in range(MAX_LINKS_PER_MESSAGE + 2))
        message = make_message(urls_text)
        client = make_client()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            async def fake_download(filename):
                open(filename, "wb").close()
                return filename
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {}})
            MockDownloader.return_value.download = AsyncMock(side_effect=fake_download)

            await handler(client, message)

        first_reply_text = message.reply.await_args_list[0].args[0]
        assert "Нашёл" in first_reply_text
        assert client.send_video.await_count == MAX_LINKS_PER_MESSAGE

    @pytest.mark.asyncio
    async def test_rapid_second_request_is_rate_limited(self):
        handler, db = _register()
        message1 = make_message(URL, user_id=55)
        message2 = make_message(URL, user_id=55)
        client = make_client()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            async def fake_download(filename):
                open(filename, "wb").close()
                return filename
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {}})
            MockDownloader.return_value.download = AsyncMock(side_effect=fake_download)

            await handler(client, message1)
            await handler(client, message2)  # right after — should be throttled

        assert client.send_video.await_count == 1
        assert "Подожди ещё" in message2.reply.await_args.args[0]


class TestTikTokSlideshow:
    URL = "https://www.tiktok.com/@user/photo/789"

    @pytest.mark.asyncio
    async def test_slideshow_sends_media_group_not_video(self, tmp_path):
        handler, db = _register()
        message = make_message(self.URL)
        client = make_client()
        client.send_media_group = AsyncMock()

        image_paths = [str(tmp_path / f"img{i}.jpg") for i in range(3)]
        for p in image_paths:
            open(p, "wb").close()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {"images": image_paths}})
            MockDownloader.return_value.download_slideshow = AsyncMock(return_value=image_paths)

            await handler(client, message)

        client.send_video.assert_not_called()
        client.send_media_group.assert_awaited_once()
        sent_media = client.send_media_group.await_args.args[1]
        assert len(sent_media) == 3
        db.log_download.assert_called_once_with(message.from_user.id, "tiktok", self.URL)

    @pytest.mark.asyncio
    async def test_slideshow_chunks_more_than_ten_images(self, tmp_path):
        handler, db = _register()
        message = make_message(self.URL)
        client = make_client()
        client.send_media_group = AsyncMock()

        image_paths = [str(tmp_path / f"img{i}.jpg") for i in range(13)]
        for p in image_paths:
            open(p, "wb").close()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()):
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {"images": image_paths}})
            MockDownloader.return_value.download_slideshow = AsyncMock(return_value=image_paths)

            await handler(client, message)

        assert client.send_media_group.await_count == 2  # 10 + 3
        first_chunk = client.send_media_group.await_args_list[0].args[1]
        second_chunk = client.send_media_group.await_args_list[1].args[1]
        assert len(first_chunk) == 10
        assert len(second_chunk) == 3

    @pytest.mark.asyncio
    async def test_slideshow_cleans_up_temp_directory(self, tmp_path):
        handler, db = _register()
        message = make_message(self.URL)
        client = make_client()
        client.send_media_group = AsyncMock()

        image_paths = [str(tmp_path / f"img{i}.jpg") for i in range(2)]
        for p in image_paths:
            open(p, "wb").close()

        with patch("handlers.tiktok.TikTokDownloader") as MockDownloader, \
             patch("handlers.tiktok.asyncio.sleep", new=AsyncMock()), \
             patch("handlers.tiktok.shutil.rmtree") as mock_rmtree:
            MockDownloader.return_value.probe = AsyncMock(return_value={"data": {"images": image_paths}})
            MockDownloader.return_value.download_slideshow = AsyncMock(return_value=image_paths)

            await handler(client, message)

        mock_rmtree.assert_called_once()
        assert "slideshow_" in mock_rmtree.call_args.args[0]
