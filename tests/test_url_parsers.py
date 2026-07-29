"""
Integration tests for URL parsers:
  - TikTok URL detection (is_tiktok_url)
  - YouTube URL detection (is_youtube_url)
  - YouTube URL normalization (fix_url)
  - TikTok URL extraction from message text
"""
import pytest
from unittest.mock import MagicMock

from services.downloader import is_tiktok_url, is_youtube_url, is_instagram_url, is_twitter_url
from services.youtube.youtube_downloader import fix_url


# ── TikTok URL Detection ──────────────────────────────────────────────

class TestIsTikTokUrl:
    @pytest.mark.parametrize("url", [
        "https://www.tiktok.com/@user/video/1234567890",
        "https://vm.tiktok.com/abc123/",
        "https://m.tiktok.com/@user/video/123",
        "http://tiktok.com/@foo/video/999",
        "https://www.tiktok.com/t/ZTR123abc/",
    ])
    def test_valid_tiktok_urls(self, url):
        assert is_tiktok_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=abc",
        "https://example.com/tiktok",
        "",
    ])
    def test_non_tiktok_urls(self, url):
        assert is_tiktok_url(url) is False


# ── YouTube URL Detection ─────────────────────────────────────────────

class TestIsYouTubeUrl:
    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtube.com/shorts/abc123",
        "http://youtube.com/watch?v=test",
        "https://www.youtube.com/shorts/xyz",
    ])
    def test_valid_youtube_urls(self, url):
        assert is_youtube_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://www.tiktok.com/@user/video/123",
        "https://example.com/youtube",
        "",
    ])
    def test_non_youtube_urls(self, url):
        assert is_youtube_url(url) is False


class TestIsInstagramUrl:
    @pytest.mark.parametrize("url", [
        "https://www.instagram.com/reel/DYmDjXusIte/",
        "https://instagram.com/p/ABC123/",
        "https://instagr.am/reel/XYZ/",
        "https://www.instagram.com/tv/12345/",
    ])
    def test_valid_instagram_urls(self, url):
        assert is_instagram_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://example.com/instagram",
        "",
    ])
    def test_non_instagram_urls(self, url):
        assert is_instagram_url(url) is False


class TestIsTwitterUrl:
    @pytest.mark.parametrize("url", [
        "https://x.com/NASA/status/2038767984060063896",
        "https://twitter.com/NASA/status/2038767984060063896",
        "https://www.twitter.com/user/status/123",
        "https://mobile.twitter.com/user/status/123",
    ])
    def test_valid_twitter_urls(self, url):
        assert is_twitter_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://x.com/NASA",  # profile page, not a tweet
        "https://example.com/x.com/status/1",
        "",
    ])
    def test_non_twitter_urls(self, url):
        assert is_twitter_url(url) is False


# ── YouTube URL Normalization (fix_url) ────────────────────────────────

class TestFixUrl:
    @pytest.mark.parametrize("input_url, expected_id", [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/shorts/abc123", "abc123"),
        ("https://www.youtube.com/watch?v=test&list=PLxyz", "test"),
        ("http://youtube.com/watch?v=V1d&t=120", "V1d"),
    ])
    def test_normalizes_to_standard_url(self, input_url, expected_id):
        result = fix_url(input_url)
        assert result == f"https://youtube.com/watch?v={expected_id}"

    @pytest.mark.parametrize("bad_url", [
        "https://youtube.com/channel/UCxyz",
        "https://youtube.com/playlist?list=PLabc",
        "https://youtube.com/",
    ])
    def test_raises_for_invalid_urls(self, bad_url):
        with pytest.raises(ValueError, match="video_id"):
            fix_url(bad_url)


# ── TikTok URL Extraction from message text ────────────────────────────

class TestTikTokExtractUrl:
    def test_extracts_url_from_text(self):
        from services.downloader import extract_url
        assert extract_url("Check this out https://www.tiktok.com/@user/video/123 nice!") == "https://www.tiktok.com/@user/video/123"

    def test_extracts_first_url(self):
        from services.downloader import extract_url
        assert extract_url("https://example.com https://vm.tiktok.com/abc") == "https://example.com"

    def test_returns_none_for_no_url(self):
        from services.downloader import extract_url
        assert extract_url("no links here") is None

    def test_returns_none_for_empty(self):
        from services.downloader import extract_url
        assert extract_url("") is None


class TestExtractUrls:
    def test_extracts_single_url(self):
        from services.downloader import extract_urls
        assert extract_urls("Check this https://www.tiktok.com/@user/video/123 nice!") == [
            "https://www.tiktok.com/@user/video/123"
        ]

    def test_extracts_multiple_urls_in_order(self):
        from services.downloader import extract_urls
        text = "https://vm.tiktok.com/abc https://youtu.be/xyz and https://instagram.com/p/qwe/"
        assert extract_urls(text) == [
            "https://vm.tiktok.com/abc",
            "https://youtu.be/xyz",
            "https://instagram.com/p/qwe/",
        ]

    def test_returns_empty_list_for_no_urls(self):
        from services.downloader import extract_urls
        assert extract_urls("no links here") == []

    def test_returns_empty_list_for_empty_string(self):
        from services.downloader import extract_urls
        assert extract_urls("") == []

    def test_returns_empty_list_for_none(self):
        from services.downloader import extract_urls
        assert extract_urls(None) == []
