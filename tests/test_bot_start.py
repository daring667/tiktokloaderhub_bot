# tests/test_bot_start.py
"""Startup wiring checks.

This used to assert that BOT_TOKEN/API_KEY/API_HASH were set — which proved
nothing, since CI supplies those very values itself in the workflow. These
check the things that actually break a start: every handler module imports
cleanly and exposes the entry point main.py calls.
"""
import importlib

import pytest


@pytest.mark.parametrize("module_name", [
    "handlers.youtube",
    "handlers.instagram",
    "handlers.twitter",
])
def test_handler_module_exposes_register(module_name):
    module = importlib.import_module(module_name)
    assert callable(module.register)


def test_tiktok_handler_exposes_register():
    from handlers.tiktok import TikTokHandler
    assert callable(TikTokHandler.register)


@pytest.mark.parametrize("module_name", [
    "services.downloader",
    "services.database",
    "services.tiktok.tiktok_downloader",
    "services.youtube.youtube_downloader",
    "services.instagram.instagram_downloader",
    "services.twitter.twitter_downloader",
    "services.utils.broadcast",
    "services.utils.env",
    "services.utils.version",
    "services.utils.progress_bar",
    "services.utils.sanitize",
])
def test_service_module_imports(module_name):
    assert importlib.import_module(module_name) is not None
