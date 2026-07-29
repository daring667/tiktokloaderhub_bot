"""
Mock-based tests for Twitter/X downloader.
"""
import os
import pytest
from unittest.mock import patch, MagicMock


class TestTwitterDownloaderInit:
    FAKE_URL = "https://x.com/NASA/status/2038767984060063896"

    @patch("services.twitter.twitter_downloader.yt_dlp.YoutubeDL")
    def test_parses_twitter_metadata(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Tweet Video",
            "id": "2038767984060063896",
        }
        mock_ydl_class.return_value = mock_ydl

        from services.twitter.twitter_downloader import TwitterDownloader
        dl = TwitterDownloader(self.FAKE_URL)

        assert dl.title == "Test Tweet Video"

    @patch("services.twitter.twitter_downloader.yt_dlp.YoutubeDL")
    def test_missing_info_raises(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = None
        mock_ydl_class.return_value = mock_ydl

        from services.twitter.twitter_downloader import TwitterDownloader
        with pytest.raises(ValueError, match="Не удалось получить информацию"):
            TwitterDownloader(self.FAKE_URL)

    @patch("services.twitter.twitter_downloader.yt_dlp.YoutubeDL")
    def test_download_error_raises_value_error(self, mock_ydl_class):
        from yt_dlp.utils import DownloadError
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = DownloadError("boom")
        mock_ydl_class.return_value = mock_ydl

        from services.twitter.twitter_downloader import TwitterDownloader
        with pytest.raises(ValueError, match="не смог распарсить"):
            TwitterDownloader(self.FAKE_URL)


class TestTwitterDownloaderDownload:
    FAKE_URL = "https://x.com/NASA/status/2038767984060063896"

    @patch("services.twitter.twitter_downloader.yt_dlp.YoutubeDL")
    @pytest.mark.asyncio
    async def test_download_returns_mp4_path(self, mock_ydl_class, tmp_path):
        probe_ydl = MagicMock()
        probe_ydl.__enter__ = MagicMock(return_value=probe_ydl)
        probe_ydl.__exit__ = MagicMock(return_value=False)
        probe_ydl.extract_info.return_value = {"title": "Test", "id": "123"}

        download_ydl = MagicMock()

        mock_ydl_class.side_effect = [probe_ydl, download_ydl]

        from services.twitter.twitter_downloader import TwitterDownloader
        dl = TwitterDownloader(self.FAKE_URL)

        output = str(tmp_path / "video.mp4")

        def fake_download(urls):
            (tmp_path / "video.mp4").write_bytes(b"fake")

        download_ydl.download.side_effect = fake_download

        result = await dl.download(output)
        assert result == output
        assert os.path.exists(result)
