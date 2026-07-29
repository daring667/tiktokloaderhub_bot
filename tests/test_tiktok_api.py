"""
Mock-based tests for TikTok API interactions.
Tests download_tiktok_video from services/downloader.py (pure function, no Pyrogram).
"""
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import aiohttp
import asyncio

from services.downloader import download_tiktok_video

class TestDownloadTikTokVideo:
    """Test download_tiktok_video with mocked aiohttp."""

    FAKE_URL = "https://www.tiktok.com/@user/video/1234567890"

    def _mock_tikwm_response(self, video_url="https://v.tikwm.com/video.mp4"):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"data": {"play": video_url}}
        mock_resp.raise_for_status = MagicMock()
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        return mock_ctx

    def _mock_video_response(self, content=b"fake_video_data"):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = MagicMock()
        
        async def iter_chunked(size):
            yield content
            
        mock_resp.content.iter_chunked = iter_chunked
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        return mock_ctx

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_successful_download(self, mock_get, tmp_path):
        """Successful tikwm API call + video download."""
        api_resp = self._mock_tikwm_response()
        video_resp = self._mock_video_response()

        # First call = API metadata, second call = video stream
        mock_get.side_effect = [api_resp, video_resp]

        output = str(tmp_path / "video.mp4")
        result = await download_tiktok_video(self.FAKE_URL, output)

        assert result == output
        assert os.path.exists(output)

        with open(output, "rb") as f:
            assert f.read() == b"fake_video_data"

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_empty_play_url_raises_value_error(self, mock_get):
        """API returns empty data.play → ValueError."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"data": {"play": None}}
        mock_resp.raise_for_status = MagicMock()
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_get.return_value = mock_ctx

        with pytest.raises(ValueError, match="Не удалось получить видео из ответа API"):
            await download_tiktok_video(self.FAKE_URL, "/tmp/out.mp4")

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_missing_data_key_raises_value_error(self, mock_get):
        """API returns empty response → ValueError."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status = MagicMock()
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_get.return_value = mock_ctx

        with pytest.raises(ValueError, match="Не удалось получить видео из ответа API"):
            await download_tiktok_video(self.FAKE_URL, "/tmp/out.mp4")

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_http_error_propagates(self, mock_get):
        """HTTP 500 from API → ClientResponseError."""
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=500, message="500 Server Error"
        )
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_get.return_value = mock_ctx

        with pytest.raises(aiohttp.ClientResponseError):
            await download_tiktok_video(self.FAKE_URL, "/tmp/out.mp4")

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_timeout_propagates(self, mock_get):
        """Network timeout → TimeoutError."""
        mock_get.side_effect = asyncio.TimeoutError("Read timed out")

        with pytest.raises(asyncio.TimeoutError):
            await download_tiktok_video(self.FAKE_URL, "/tmp/out.mp4")

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_connection_error_propagates(self, mock_get):
        """Network unreachable → ClientConnectionError."""
        mock_get.side_effect = aiohttp.ClientConnectionError("Connection refused")

        with pytest.raises(aiohttp.ClientConnectionError):
            await download_tiktok_video(self.FAKE_URL, "/tmp/out.mp4")

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_downloader_class_successful_download(self, mock_get, tmp_path):
        """Successful download using TikTokDownloader class."""
        from services.tiktok.tiktok_downloader import TikTokDownloader
        api_resp = self._mock_tikwm_response()
        video_resp = self._mock_video_response()

        mock_get.side_effect = [api_resp, video_resp]

        output = str(tmp_path / "video.mp4")
        downloader = TikTokDownloader(self.FAKE_URL)
        result = await downloader.download(output)

        assert result == output
        assert os.path.exists(output)

        with open(output, "rb") as f:
            assert f.read() == b"fake_video_data"

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_downloader_class_oversized_raises_value_error(self, mock_get, tmp_path):
        """Oversized video (>50MB) raises ValueError in TikTokDownloader."""
        from services.tiktok.tiktok_downloader import TikTokDownloader
        
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"data": {"play": "https://v.tikwm.com/video.mp4", "size": 60 * 1024 * 1024}}
        mock_resp.raise_for_status = MagicMock()
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_get.return_value = mock_ctx

        downloader = TikTokDownloader(self.FAKE_URL)
        with pytest.raises(ValueError, match="Видео слишком большое"):
            await downloader.download(str(tmp_path / "too_big.mp4"))


class TestTikTokSlideshow:
    """TikTok photo posts: tikwm returns images[] instead of a video play URL."""

    FAKE_URL = "https://www.tiktok.com/@user/photo/456"

    def _mock_video_response_json(self, play_url="https://v.tikwm.com/video.mp4"):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"data": {"play": play_url}}
        mock_resp.raise_for_status = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        return mock_ctx

    def _mock_slideshow_response_json(self, image_urls):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {
            "data": {"images": image_urls, "play": "https://v.tikwm.com/music.mp3"}
        }
        mock_resp.raise_for_status = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        return mock_ctx

    def _mock_binary_response(self, content=b"fake_bytes"):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = MagicMock()

        async def iter_chunked(size):
            yield content

        mock_resp.content.iter_chunked = iter_chunked
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        return mock_ctx

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_download_raises_for_slideshow_post(self, mock_get, tmp_path):
        """download() is for videos — a slideshow post must raise, not
        silently download the background music as if it were a video."""
        from services.tiktok.tiktok_downloader import TikTokDownloader
        mock_get.return_value = self._mock_slideshow_response_json(
            ["https://img.example/1.jpg", "https://img.example/2.jpg"]
        )

        downloader = TikTokDownloader(self.FAKE_URL)
        with pytest.raises(ValueError, match="слайдшоу"):
            await downloader.download(str(tmp_path / "video.mp4"))

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_download_slideshow_saves_all_images_in_order(self, mock_get, tmp_path):
        from services.tiktok.tiktok_downloader import TikTokDownloader
        api_resp = self._mock_slideshow_response_json([
            "https://img.example/1.jpg", "https://img.example/2.jpg", "https://img.example/3.jpg",
        ])
        mock_get.side_effect = [
            api_resp,
            self._mock_binary_response(b"img1"),
            self._mock_binary_response(b"img2"),
            self._mock_binary_response(b"img3"),
        ]

        downloader = TikTokDownloader(self.FAKE_URL)
        paths = await downloader.download_slideshow(str(tmp_path / "slideshow"))

        assert len(paths) == 3
        for path, expected in zip(paths, [b"img1", b"img2", b"img3"]):
            assert os.path.exists(path)
            with open(path, "rb") as f:
                assert f.read() == expected

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_download_slideshow_raises_for_video_post(self, mock_get, tmp_path):
        from services.tiktok.tiktok_downloader import TikTokDownloader
        mock_get.return_value = self._mock_video_response_json()

        downloader = TikTokDownloader(self.FAKE_URL)
        with pytest.raises(ValueError, match="не фото-слайдшоу"):
            await downloader.download_slideshow(str(tmp_path / "slideshow"))

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession.get")
    async def test_probe_is_cached_across_calls(self, mock_get, tmp_path):
        """probe() should only hit the API once, even if called again by
        download_slideshow() afterwards."""
        from services.tiktok.tiktok_downloader import TikTokDownloader
        api_resp = self._mock_slideshow_response_json(["https://img.example/1.jpg"])
        mock_get.side_effect = [api_resp, self._mock_binary_response()]

        downloader = TikTokDownloader(self.FAKE_URL)
        await downloader.probe()
        await downloader.download_slideshow(str(tmp_path / "slideshow"))

        # 1 API call (cached on the 2nd probe() inside download_slideshow) + 1 image download
        assert mock_get.call_count == 2
