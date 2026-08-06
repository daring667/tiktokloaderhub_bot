"""Retry behaviour of the TikTok downloader.

Came from a real failure: a connection timeout to v45.tiktokcdn-us.com with
a five-second connect budget, from a phone on mobile data. One attempt, no
retry, and the user got "таймаут, попробуй позже" for what was almost
certainly a blip.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

import aiohttp

from services.tiktok import tiktok_downloader as td


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(td, "RETRY_BACKOFF_SECONDS", 0)


class TestWithRetry:
    @pytest.mark.asyncio
    async def test_a_first_time_success_is_not_retried(self):
        calls = []

        async def attempt():
            calls.append(1)
            return "ok"

        assert await td._with_retry(attempt, "тест") == "ok"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_a_blip_is_survived(self):
        calls = []

        async def attempt():
            calls.append(1)
            if len(calls) == 1:
                raise aiohttp.ClientConnectionError("connection reset")
            return "ok"

        assert await td._with_retry(attempt, "тест") == "ok"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_a_connection_timeout_is_retried(self):
        """The exact failure this was written for."""
        calls = []

        async def attempt():
            calls.append(1)
            if len(calls) == 1:
                raise aiohttp.ClientConnectionError("Connection timeout to host")
            return "ok"

        assert await td._with_retry(attempt, "тест") == "ok"

    @pytest.mark.asyncio
    async def test_it_gives_up_after_the_second_failure(self):
        calls = []

        async def attempt():
            calls.append(1)
            raise asyncio.TimeoutError()

        with pytest.raises(asyncio.TimeoutError):
            await td._with_retry(attempt, "тест")
        assert len(calls) == td.NETWORK_ATTEMPTS == 2

    @pytest.mark.asyncio
    async def test_an_http_error_is_not_retried(self):
        """A 404 will be a 404 again. Repeating it only makes the user wait
        twice as long for the same answer."""
        calls = []

        async def attempt():
            calls.append(1)
            raise aiohttp.ClientResponseError(None, (), status=404)

        with pytest.raises(aiohttp.ClientResponseError):
            await td._with_retry(attempt, "тест")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_a_value_error_is_not_retried(self):
        calls = []

        async def attempt():
            calls.append(1)
            raise ValueError("это слайдшоу")

        with pytest.raises(ValueError):
            await td._with_retry(attempt, "тест")
        assert len(calls) == 1


class TestConnectBudget:
    def test_connect_timeout_leaves_room_for_a_slow_handshake(self):
        """Five seconds was the whole problem: a CDN on another continent
        reached over mobile data can take longer than that just to connect."""
        assert td.CONNECT_TIMEOUT >= 10


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_a_retried_download_does_not_append_to_the_first_attempt(self, tmp_path):
        """The retry reopens the file with "wb", so a partial first attempt
        is truncated rather than left as a prefix of the second."""
        target = tmp_path / "video.mp4"
        attempts = []

        class FakeContent:
            def __init__(self, chunks):
                self._chunks = chunks

            async def iter_chunked(self, _size):
                for chunk in self._chunks:
                    yield chunk

        class FakeResponse:
            def __init__(self, chunks, fail):
                self.content = FakeContent(chunks)
                self._fail = fail

            def raise_for_status(self):
                pass

            async def __aenter__(self):
                if self._fail:
                    raise aiohttp.ClientConnectionError("dropped")
                return self

            async def __aexit__(self, *exc):
                return False

        class FakeSession:
            def get(self, *a, **k):
                first = not attempts
                attempts.append(1)
                # First attempt writes nothing and dies; second succeeds.
                return FakeResponse([b"good"], fail=first)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        with patch.object(td.aiohttp, "ClientSession", lambda *a, **k: FakeSession()):
            downloader = td.TikTokDownloader("https://vt.tiktok.com/x/")
            await downloader._download_file("https://cdn/video.mp4", str(target))

        assert len(attempts) == 2
        assert target.read_bytes() == b"good"
