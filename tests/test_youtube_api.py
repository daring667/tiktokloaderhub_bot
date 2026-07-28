"""
Mock-based tests for YouTube API interactions.
Tests YouTubeDownloader initialization with mocked yt_dlp.
"""
import pytest
from unittest.mock import patch, MagicMock

from yt_dlp.utils import DownloadError


class TestYouTubeDownloaderInit:
    """Test YouTubeDownloader metadata parsing with mocked yt_dlp."""

    FAKE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def _mock_info(self, **overrides):
        """Build a plausible yt-dlp info dict."""
        info = {
            "title": "Test Video",
            "duration": 180,
            "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
            "formats": [
                {
                    "format_id": "18",
                    "format_note": "360p",
                    "ext": "mp4",
                    "acodec": "mp4a.40.2",
                    "vcodec": "avc1.42001E",
                    "filesize": 15_000_000,
                    "resolution": "640x360",
                },
                {
                    "format_id": "22",
                    "format_note": "720p",
                    "ext": "mp4",
                    "acodec": "mp4a.40.2",
                    "vcodec": "avc1.64001F",
                    "filesize": 45_000_000,
                    "resolution": "1280x720",
                },
                {
                    "format_id": "251",
                    "format_note": "audio only",
                    "ext": "webm",
                    "acodec": "opus",
                    "vcodec": "none",
                    "filesize": 3_500_000,
                },
            ],
        }
        info.update(overrides)
        return info

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_parses_video_metadata(self, mock_ydl_class, mock_cookies):
        """YouTubeDownloader correctly parses title, length, thumbnail, streams."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = self._mock_info()
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        dl = YouTubeDownloader(self.FAKE_URL)

        assert dl.title == "Test Video"
        assert dl.length == 180
        assert dl.thumbnail is not None

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_collects_progressive_streams(self, mock_ydl_class, mock_cookies):
        """Progressive streams (audio+video) are collected."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = self._mock_info()
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        dl = YouTubeDownloader(self.FAKE_URL)

        video_streams = [s for s in dl.streams if s["type"] == "video"]
        audio_streams = [s for s in dl.streams if s["type"] == "audio"]

        assert len(video_streams) == 2
        assert len(audio_streams) == 1  # bestaudio option
        assert audio_streams[0]["itag"] == "bestaudio"

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_no_formats_raises_value_error(self, mock_ydl_class, mock_cookies):
        """No suitable formats → ValueError."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        # All formats are video-only (no audio codec)
        mock_ydl.extract_info.return_value = self._mock_info(formats=[
            {"format_id": "137", "acodec": "none", "vcodec": "avc1", "filesize": 50_000_000}
        ])
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        with pytest.raises(ValueError):
            YouTubeDownloader(self.FAKE_URL)

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_download_error_raises_value_error(self, mock_ydl_class, mock_cookies):
        """yt-dlp DownloadError → ValueError."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = DownloadError("Video unavailable")
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        with pytest.raises(ValueError, match="yt-dlp"):
            YouTubeDownloader(self.FAKE_URL)

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_extract_info_returns_none_raises(self, mock_ydl_class, mock_cookies):
        """extract_info returns None → ValueError."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = None
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        with pytest.raises(ValueError):
            YouTubeDownloader(self.FAKE_URL)

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_streams_sorted_by_filesize_desc(self, mock_ydl_class, mock_cookies):
        """Streams are sorted by filesize descending (largest first)."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = self._mock_info()
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        dl = YouTubeDownloader(self.FAKE_URL)

        filesizes = [s["filesize"] or 0 for s in dl.streams]
        assert filesizes == sorted(filesizes, reverse=True)
