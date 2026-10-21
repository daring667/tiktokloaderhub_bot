"""
Mock-based tests for YouTube API interactions.
Tests YouTubeDownloader initialization with mocked yt_dlp.
"""
import asyncio
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
    def test_builds_merged_video_stream_for_adaptive_formats(self, mock_ydl_class, mock_cookies):
        """Video-only and audio-only YouTube streams are offered as a video."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = self._mock_info(formats=[
            {"format_id": "137", "format_note": "1080p", "acodec": "none",
             "vcodec": "avc1", "height": 1080, "filesize": 40_000_000},
            {"format_id": "251", "format_note": "audio only", "acodec": "opus",
             "vcodec": "none", "filesize": 4_000_000},
        ])
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        dl = YouTubeDownloader(self.FAKE_URL)

        video_streams = [s for s in dl.streams if s["type"] == "video"]
        assert len(video_streams) == 1
        assert video_streams[0]["itag"] == "137+251"
        assert video_streams[0]["filesize"] == 44_000_000

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_adaptive_video_with_unknown_size_is_not_reported_as_audio_size(self, mock_ydl_class, mock_cookies):
        """A missing video filesize must not be mistaken for a small result."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = self._mock_info(formats=[
            {"format_id": "137", "format_note": "1080p", "acodec": "none",
             "vcodec": "avc1", "ext": "mp4", "height": 1080},
            {"format_id": "140", "format_note": "audio only", "acodec": "mp4a",
             "vcodec": "none", "ext": "m4a", "filesize": 8_000_000},
        ])
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        stream = next(
            item for item in YouTubeDownloader(self.FAKE_URL).get_available_formats()
            if item["type"] == "video"
        )

        assert stream["itag"] == "137+140"
        assert stream["filesize"] is None

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_adaptive_formats_prefer_known_size_per_quality(self, mock_ydl_class, mock_cookies):
        """The safe 360p default must not be replaced by an unknown-size variant."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = self._mock_info(formats=[
            {"format_id": "230", "format_note": "360p", "acodec": "none",
             "vcodec": "avc1", "ext": "mp4", "height": 360, "tbr": 800},
            {"format_id": "134", "format_note": "360p", "acodec": "none",
             "vcodec": "avc1", "ext": "mp4", "height": 360, "tbr": 550,
             "filesize": 37_000_000},
            {"format_id": "140", "format_note": "audio only", "acodec": "mp4a",
             "vcodec": "none", "ext": "m4a", "filesize": 8_000_000},
        ])
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        stream = YouTubeDownloader(self.FAKE_URL).get_available_formats()[0]

        assert stream["itag"] == "134+140"
        assert stream["height"] == 360
        assert stream["filesize"] == 45_000_000

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_retry_without_cookiefile_on_reload_error(self, mock_ydl_class, mock_cookies):
        """YouTube reload errors should retry without stale cookies."""
        first_ydl = MagicMock()
        first_ydl.__enter__ = MagicMock(return_value=first_ydl)
        first_ydl.__exit__ = MagicMock(return_value=False)
        first_ydl.extract_info.side_effect = DownloadError("ERROR: [youtube] ITXVIK8KZuI: The page needs to be reloaded.")

        second_ydl = MagicMock()
        second_ydl.__enter__ = MagicMock(return_value=second_ydl)
        second_ydl.__exit__ = MagicMock(return_value=False)
        second_ydl.extract_info.return_value = self._mock_info()

        mock_ydl_class.side_effect = [first_ydl, second_ydl]

        from services.youtube.youtube_downloader import YouTubeDownloader
        dl = YouTubeDownloader(self.FAKE_URL)

        assert dl.title == "Test Video"
        assert mock_ydl_class.call_count == 2

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_download_error_raises_value_error(self, mock_ydl_class, mock_cookies):
        """yt-dlp DownloadError → ValueError."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = DownloadError("something unheard of")
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


class TestIsPlaylistUrl:
    def test_pure_playlist_url(self):
        from services.youtube.youtube_downloader import is_playlist_url
        assert is_playlist_url("https://www.youtube.com/playlist?list=PLxyz") is True

    def test_video_with_list_param_is_not_a_playlist(self):
        """A single video opened from within a playlist should still be
        treated as one video, not the whole playlist."""
        from services.youtube.youtube_downloader import is_playlist_url
        assert is_playlist_url("https://www.youtube.com/watch?v=abc123&list=PLxyz") is False

    def test_plain_video_url(self):
        from services.youtube.youtube_downloader import is_playlist_url
        assert is_playlist_url("https://www.youtube.com/watch?v=abc123") is False


class TestGetPlaylistInfo:
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_returns_title_urls_and_total(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "My Playlist",
            "entries": [{"id": "aaa"}, {"id": "bbb"}, {"id": "ccc"}],
        }
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import get_playlist_info
        title, urls, total = get_playlist_info("https://www.youtube.com/playlist?list=PLxyz")

        assert title == "My Playlist"
        assert total == 3
        assert urls == [
            "https://youtube.com/watch?v=aaa",
            "https://youtube.com/watch?v=bbb",
            "https://youtube.com/watch?v=ccc",
        ]

    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_caps_urls_at_limit_but_reports_true_total(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Big Playlist",
            "entries": [{"id": f"v{i}"} for i in range(10)],
        }
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import get_playlist_info
        title, urls, total = get_playlist_info("https://www.youtube.com/playlist?list=PLxyz", limit=3)

        assert total == 10
        assert len(urls) == 3

    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_empty_playlist_raises_value_error(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"title": "Empty", "entries": []}
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import get_playlist_info
        with pytest.raises(ValueError, match="пуст"):
            get_playlist_info("https://www.youtube.com/playlist?list=PLxyz")

    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_download_error_raises_value_error(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = DownloadError("boom")
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import get_playlist_info
        with pytest.raises(ValueError, match="не смог распарсить"):
            get_playlist_info("https://www.youtube.com/playlist?list=PLxyz")

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_download_retries_with_android_player_on_http_403(self, mock_ydl_class, mock_cookies, tmp_path):
        """A 403 during the actual download should retry with a safer YouTube client."""
        meta_ydl = MagicMock()
        meta_ydl.__enter__ = MagicMock(return_value=meta_ydl)
        meta_ydl.__exit__ = MagicMock(return_value=False)
        meta_ydl.extract_info.return_value = {
            "title": "Test Video",
            "duration": 180,
            "thumbnail": "https://example.com/thumb.jpg",
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
                    "format_id": "251",
                    "format_note": "audio only",
                    "ext": "webm",
                    "acodec": "opus",
                    "vcodec": "none",
                    "filesize": 3_500_000,
                },
            ],
        }

        first_download_ydl = MagicMock()
        first_download_ydl.download.side_effect = DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")

        second_download_ydl = MagicMock()
        second_download_ydl.download.return_value = None

        mock_ydl_class.side_effect = [meta_ydl, first_download_ydl, second_download_ydl]

        out_path = tmp_path / "Test Video.mp4"
        out_path.write_bytes(b"video-bytes")

        from services.youtube.youtube_downloader import YouTubeDownloader
        dl = YouTubeDownloader("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        result = asyncio.run(dl.download("18", str(tmp_path / "Test Video.mp4")))

        assert result == str(tmp_path / "Test Video.mp4")
        assert mock_ydl_class.call_count == 3


class TestPreferredAudioLanguage:
    """YouTube serves the original track plus auto-dubs; we want one language.

    The picker used to be ``max(..., key=filesize)``, which ignored language
    entirely — a Russian video whose English auto-dub happened to encode a few
    kilobytes larger was silently downloaded with English audio.
    """

    FAKE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    @staticmethod
    def _audio(format_id, language, filesize, langpref=-1, ext="m4a"):
        return {
            "format_id": format_id, "ext": ext, "acodec": "mp4a",
            "vcodec": "none", "language": language, "filesize": filesize,
            "language_preference": langpref,
        }

    def test_picks_russian_dub_over_larger_original(self):
        """An English original must not win just by being the fattest track."""
        from services.youtube.youtube_downloader import pick_audio_format
        formats = [
            self._audio("140-20", "en", 9_000_000, langpref=10),
            self._audio("140-11", "ru", 8_000_000),
        ]
        assert pick_audio_format(formats, "ru")["format_id"] == "140-11"

    def test_picks_russian_original_over_larger_english_dub(self):
        """The reported bug: ru original is smaller than its en auto-dub."""
        from services.youtube.youtube_downloader import pick_audio_format
        formats = [
            self._audio("140-0", "en-US", 890_305),
            self._audio("140-1", "ru", 888_803, langpref=10),
        ]
        assert pick_audio_format(formats, "ru")["format_id"] == "140-1"

    def test_matches_regional_language_codes(self):
        """"ru" must also match a "ru-RU" track."""
        from services.youtube.youtube_downloader import pick_audio_format
        formats = [
            self._audio("140-0", "en-US", 900_000, langpref=10),
            self._audio("140-1", "ru-RU", 100_000),
        ]
        assert pick_audio_format(formats, "ru")["format_id"] == "140-1"

    def test_prefers_m4a_over_webm_within_the_language(self):
        """Opus in mp4 plays worse in Telegram clients than AAC."""
        from services.youtube.youtube_downloader import pick_audio_format
        formats = [
            self._audio("251-11", "ru", 9_000_000, ext="webm"),
            self._audio("140-11", "ru", 8_000_000, ext="m4a"),
        ]
        assert pick_audio_format(formats, "ru")["format_id"] == "140-11"

    def test_falls_back_to_original_when_language_absent(self):
        """With no Russian track, the original beats any dub."""
        from services.youtube.youtube_downloader import pick_audio_format
        formats = [
            self._audio("140-0", "de", 9_000_000),
            self._audio("140-1", "en", 8_000_000, langpref=10),
        ]
        assert pick_audio_format(formats, "ru")["format_id"] == "140-1"

    def test_empty_input_returns_none(self):
        from services.youtube.youtube_downloader import pick_audio_format
        assert pick_audio_format([], "ru") is None

    def test_a_plain_track_beats_its_drc_twin(self):
        """DRC is a loudness-compressed copy; it used to win on size alone.

        These variants carry no language at all, so the language filter never
        excluded them: on a video where nothing is language-tagged the pool
        falls back to everything and the fattest m4a won.
        """
        from services.youtube.youtube_downloader import pick_audio_format
        formats = [
            self._audio("140-drc", None, 9_000_000),
            self._audio("140", None, 8_000_000),
        ]
        assert pick_audio_format(formats, "ru")["format_id"] == "140"

    def test_drc_is_recognised_by_its_note_too(self):
        from services.youtube.youtube_downloader import pick_audio_format
        plain = self._audio("251", None, 8_000_000)
        drc = self._audio("252", None, 9_000_000)
        drc["format_note"] = "medium, DRC"
        assert pick_audio_format([drc, plain], "ru")["format_id"] == "251"

    def test_container_still_outranks_drc(self):
        """Compressed dynamics beat audio half the clients play badly."""
        from services.youtube.youtube_downloader import pick_audio_format
        formats = [
            self._audio("251", None, 9_000_000, ext="webm"),
            self._audio("140-drc", None, 8_000_000, ext="m4a"),
        ]
        assert pick_audio_format(formats, "ru")["format_id"] == "140-drc"

    def test_language_still_outranks_everything(self):
        """A DRC track in the wanted language beats a plain one that is not."""
        from services.youtube.youtube_downloader import pick_audio_format
        formats = [
            self._audio("140", "en", 9_000_000, langpref=10),
            self._audio("140-drc", "ru", 1_000_000),
        ]
        assert pick_audio_format(formats, "ru")["format_id"] == "140-drc"

    def test_is_drc_detection(self):
        from services.youtube.youtube_downloader import _is_drc
        assert _is_drc({"format_id": "140-drc"}) is True
        assert _is_drc({"format_id": "251", "format_note": "medium, DRC"}) is True
        assert _is_drc({"format_id": "140"}) is False
        assert _is_drc({}) is False

    def test_disabled_preference_keeps_original(self):
        """An empty PREFERRED_AUDIO_LANG leaves the choice to the original."""
        from services.youtube.youtube_downloader import pick_audio_format
        formats = [
            self._audio("140-0", "en", 100, langpref=10),
            self._audio("140-1", "ru", 9_000_000),
        ]
        assert pick_audio_format(formats, "")["format_id"] == "140-0"

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_adaptive_itag_carries_the_russian_track(self, mock_ydl_class, mock_cookies):
        """The quality picker's itag must reference the Russian audio id."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Video", "duration": 60, "thumbnail": None,
            "formats": [
                {"format_id": "137", "format_note": "1080p", "acodec": "none",
                 "vcodec": "avc1", "ext": "mp4", "height": 1080,
                 "filesize": 40_000_000},
                self._audio("140-0", "en-US", 9_000_000),
                self._audio("140-1", "ru", 8_000_000, langpref=10),
            ],
        }
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        dl = YouTubeDownloader(self.FAKE_URL)

        video = next(s for s in dl.streams if s["type"] == "video")
        assert video["itag"] == "137+140-1"
        assert dl.audio_itag == "140-1"

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_progressive_is_dropped_when_a_dub_is_available(self, mock_ydl_class, mock_cookies):
        """A progressive file only ever carries the original audio.

        When the wanted language exists as a separate dubbed track, the
        adaptive path is the only way to actually get it into the file.
        """
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Video", "duration": 60, "thumbnail": None,
            "formats": [
                {"format_id": "18", "format_note": "360p", "acodec": "mp4a",
                 "vcodec": "avc1", "ext": "mp4", "height": 360,
                 "filesize": 10_000_000},
                {"format_id": "137", "format_note": "1080p", "acodec": "none",
                 "vcodec": "avc1", "ext": "mp4", "height": 1080,
                 "filesize": 40_000_000},
                self._audio("140-20", "en", 9_000_000, langpref=10),
                self._audio("140-11", "ru", 8_000_000),
            ],
        }
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        dl = YouTubeDownloader(self.FAKE_URL)

        video_itags = [s["itag"] for s in dl.streams if s["type"] == "video"]
        assert "18" not in video_itags
        assert all(itag.endswith("+140-11") for itag in video_itags)

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_progressive_is_kept_when_the_original_is_already_russian(self, mock_ydl_class, mock_cookies):
        """No reason to lose a single-file download when the original fits."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Video", "duration": 60, "thumbnail": None,
            "formats": [
                {"format_id": "18", "format_note": "360p", "acodec": "mp4a",
                 "vcodec": "avc1", "ext": "mp4", "height": 360,
                 "filesize": 10_000_000},
                self._audio("140-1", "ru", 8_000_000, langpref=10),
                self._audio("140-0", "en-US", 9_000_000),
            ],
        }
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        dl = YouTubeDownloader(self.FAKE_URL)

        assert "18" in [s["itag"] for s in dl.streams if s["type"] == "video"]

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_mp3_selector_falls_back_through_language_then_default(self, mock_ydl_class, mock_cookies):
        """format_id differs per player_client, so keep language + plain fallbacks."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Video", "duration": 60, "thumbnail": None,
            "formats": [self._audio("140-1", "ru", 8_000_000, langpref=10)],
        }
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        spec = YouTubeDownloader(self.FAKE_URL)._audio_format_spec()

        assert spec == "140-1/bestaudio[language^=ru]/bestaudio/best"


class TestExplainYoutubeError:
    """Turning yt-dlp's English refusals into something a user can act on.

    Came from a real report: an age-restricted video surfaced to the person as
    "yt-dlp не смог распарсить ссылку", which reads as a broken bot, and paged
    the admin about something no amount of fixing would change. YouTube serves
    age-gated videos only to a signed-in account, and the bot's cookie jar
    holds no login cookies at all -- verified against eight player clients,
    none of which get past the gate.
    """

    @pytest.mark.parametrize("message", [
        "ERROR: [youtube] X: Sign in to confirm your age. Use --cookies",
        "This video is age-restricted and can only be played on YouTube",
    ])
    def test_an_age_gate_is_recognised_and_is_not_our_fault(self, message):
        from services.youtube.youtube_downloader import explain_youtube_error
        text, ours = explain_youtube_error(message)
        assert "возрастным ограничением" in text
        assert ours is False

    @pytest.mark.parametrize("message,fragment", [
        ("ERROR: Private video. Sign in if you've been granted access", "приватное"),
        ("ERROR: Join this channel to get access to members-only content", "спонсоров"),
        ("ERROR: Video unavailable", "недоступно"),
        ("ERROR: This video has been removed by the uploader", "удалил"),
        ("ERROR: The uploader has not made this video available in your country", "заблокировано"),
        ("ERROR: This live event will begin in 2 hours", "Трансляция"),
    ])
    def test_other_refusals_are_explained(self, message, fragment):
        from services.youtube.youtube_downloader import explain_youtube_error
        text, ours = explain_youtube_error(message)
        assert fragment in text
        assert ours is False

    def test_a_bot_check_is_ours_to_fix(self):
        """Our address or cookies got flagged -- the admin should hear it."""
        from services.youtube.youtube_downloader import explain_youtube_error
        text, ours = explain_youtube_error(
            "ERROR: Sign in to confirm you're not a bot")
        assert text
        assert ours is True

    def test_an_unknown_failure_stays_the_admin_s_problem(self):
        from services.youtube.youtube_downloader import explain_youtube_error
        text, ours = explain_youtube_error("ERROR: something entirely new")
        assert text is None
        assert ours is True

    def test_matching_ignores_case(self):
        from services.youtube.youtube_downloader import explain_youtube_error
        text, _ = explain_youtube_error("SIGN IN TO CONFIRM YOUR AGE")
        assert text is not None

    def test_it_accepts_an_exception_as_well_as_a_string(self):
        from services.youtube.youtube_downloader import explain_youtube_error
        text, _ = explain_youtube_error(
            DownloadError("Sign in to confirm your age"))
        assert text is not None


class TestUnavailableIsNotAParseFailure:

    FAKE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_an_age_gate_raises_the_quiet_exception(self, mock_ydl_class, mock_cookies):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = DownloadError(
            "ERROR: Sign in to confirm your age")
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import (
            YouTubeDownloader, VideoUnavailable)
        with pytest.raises(VideoUnavailable, match="возрастным"):
            YouTubeDownloader(self.FAKE_URL)

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_it_is_still_a_value_error_for_older_callers(self, mock_ydl_class, mock_cookies):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = DownloadError(
            "ERROR: Sign in to confirm your age")
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import YouTubeDownloader
        with pytest.raises(ValueError):
            YouTubeDownloader(self.FAKE_URL)

    @patch("services.youtube.youtube_downloader.setup_cookies")
    @patch("services.youtube.youtube_downloader.yt_dlp.YoutubeDL")
    def test_a_bot_check_stays_a_plain_value_error(self, mock_ydl_class, mock_cookies):
        """So it keeps reaching the admin through the usual path."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = DownloadError(
            "ERROR: Sign in to confirm you're not a bot")
        mock_ydl_class.return_value = mock_ydl

        from services.youtube.youtube_downloader import (
            YouTubeDownloader, VideoUnavailable)
        with pytest.raises(ValueError) as caught:
            YouTubeDownloader(self.FAKE_URL)
        assert not isinstance(caught.value, VideoUnavailable)
