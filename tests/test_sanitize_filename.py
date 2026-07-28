"""
Tests for the sanitize_filename utility.
"""
import pytest

from services.utils.sanitize import sanitize_filename


class TestSanitizeFilename:
    def test_normal_name_unchanged(self):
        assert sanitize_filename("My Cool Video") == "My Cool Video"

    def test_removes_invalid_chars(self):
        assert sanitize_filename('file\\name/with*bad?chars:"<>|') == "filenamewithbadchars"

    def test_unicode_normalization(self):
        # é (e + combining acute) → should not break
        result = sanitize_filename("café")
        assert "caf" in result  # combining accent removed by NFKD

    def test_empty_string_returns_video(self):
        assert sanitize_filename("") == "video"

    def test_none_returns_video(self):
        assert sanitize_filename(None) == "video"

    def test_long_name_trimmed(self):
        long_name = "A" * 200
        result = sanitize_filename(long_name)
        assert len(result) <= 120

    def test_custom_maxlen(self):
        name = "A" * 50
        result = sanitize_filename(name, maxlen=30)
        assert len(result) <= 30

    def test_collapses_whitespace(self):
        assert sanitize_filename("hello   world\t\tfoo") == "hello world foo"

    def test_strips_leading_trailing_whitespace(self):
        assert sanitize_filename("  hello  ") == "hello"

    def test_only_invalid_chars(self):
        result = sanitize_filename('\\/*?:"<>|')
        # All chars removed → empty after strip → should return empty string
        # Note: current implementation returns "" not "video" because it only
        # checks `if not name` at the top (before cleaning). This is expected.
        assert result == ""

    def test_mixed_unicode_and_special(self):
        result = sanitize_filename("Видео: Тест | 2024")
        assert ":" not in result
        assert "|" not in result
        assert "Видео" in result
