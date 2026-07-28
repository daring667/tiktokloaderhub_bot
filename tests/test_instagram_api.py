"""
Mock-based tests for Instagram downloader.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestInstagramDownloaderInit:
    FAKE_URL = "https://www.instagram.com/reel/DYmDjXusIte/"

    @patch("services.instagram.instagram_downloader.yt_dlp.YoutubeDL")
    def test_parses_instagram_metadata(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Reel",
            "id": "DYmDjXusIte",
        }
        mock_ydl_class.return_value = mock_ydl

        from services.instagram.instagram_downloader import InstagramDownloader
        dl = InstagramDownloader(self.FAKE_URL)

        assert dl.title == "Test Reel"

    @patch("services.instagram.instagram_downloader.yt_dlp.YoutubeDL")
    def test_missing_info_raises(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = None
        mock_ydl_class.return_value = mock_ydl

        from services.instagram.instagram_downloader import InstagramDownloader
        with pytest.raises(ValueError, match="Не удалось получить информацию"):
            InstagramDownloader(self.FAKE_URL)
