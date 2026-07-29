"""Tests for services/utils/version.py."""
from unittest.mock import patch, mock_open

from services.utils.version import get_version


def test_reads_version_from_file():
    with patch("builtins.open", mock_open(read_data="1.2.3\n")):
        assert get_version() == "1.2.3"


def test_strips_whitespace():
    with patch("builtins.open", mock_open(read_data="  1.2.3  \n\n")):
        assert get_version() == "1.2.3"


def test_missing_file_returns_unknown():
    with patch("builtins.open", side_effect=FileNotFoundError):
        assert get_version() == "unknown"
