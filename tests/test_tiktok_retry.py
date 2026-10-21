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


def _payload(images=None, play=None):
    data = {}
    if images is not None:
        data["images"] = images
    if play is not None:
        data["play"] = play
    return {"data": data}


def _http_error(status):
    return aiohttp.ClientResponseError(None, (), status=status)


class TestSignatureRefresh:
    """Came from a real failure: a 403 on one photo of a fifteen-photo post.

    tikwm hands back URLs the TikTok CDN has signed, and about one response in
    five carries a signature the CDN rejects. Which item is affected varies and
    the post itself is fine -- asking again produces working signatures. One
    unlucky signature used to fail the whole slideshow.
    """

    def _downloader(self, payloads):
        dl = td.TikTokDownloader("https://vt.tiktok.com/XXXX/")
        dl._fetch_data = AsyncMock(side_effect=list(payloads))
        return dl

    @pytest.mark.asyncio
    async def test_a_clean_download_asks_for_metadata_once(self):
        dl = self._downloader([_payload(images=["ok"])])
        dl._download_file = AsyncMock()

        await dl._download_signed(
            lambda d: d["data"]["images"][0], "/tmp/x.jpg", "фото 1")

        assert dl._fetch_data.await_count == 1
        dl._download_file.assert_awaited_once_with("ok", "/tmp/x.jpg")

    @pytest.mark.asyncio
    async def test_a_403_is_retried_with_a_freshly_signed_url(self):
        dl = self._downloader([_payload(images=["stale"]),
                               _payload(images=["fresh"])])
        tried = []

        async def download(url, filename):
            tried.append(url)
            if len(tried) == 1:
                raise _http_error(403)

        dl._download_file = AsyncMock(side_effect=download)
        await dl._download_signed(
            lambda d: d["data"]["images"][0], "/tmp/x.jpg", "фото 1")

        assert tried == ["stale", "fresh"]
        assert dl._fetch_data.await_count == 2

    @pytest.mark.parametrize("status", [401, 403, 410])
    @pytest.mark.asyncio
    async def test_every_refreshable_status_is_retried(self, status):
        dl = self._downloader([_payload(images=["stale"]),
                               _payload(images=["fresh"])])
        tried = []

        async def download(url, filename):
            tried.append(url)
            if len(tried) == 1:
                raise _http_error(status)

        dl._download_file = AsyncMock(side_effect=download)
        await dl._download_signed(
            lambda d: d["data"]["images"][0], "/tmp/x.jpg", "фото")
        assert tried == ["stale", "fresh"]

    @pytest.mark.asyncio
    async def test_a_404_is_not_retried(self):
        """It would fail again for the same reason; re-signing changes nothing."""
        dl = self._downloader([_payload(images=["gone"])])
        dl._download_file = AsyncMock(side_effect=_http_error(404))

        with pytest.raises(aiohttp.ClientResponseError):
            await dl._download_signed(
                lambda d: d["data"]["images"][0], "/tmp/x.jpg", "фото 1")

        assert dl._download_file.await_count == 1
        assert dl._fetch_data.await_count == 1

    @pytest.mark.asyncio
    async def test_it_gives_up_rather_than_looping(self):
        dl = self._downloader([_payload(images=["a"])] * td.SIGNATURE_ATTEMPTS)
        dl._download_file = AsyncMock(side_effect=_http_error(403))

        with pytest.raises(aiohttp.ClientResponseError):
            await dl._download_signed(
                lambda d: d["data"]["images"][0], "/tmp/x.jpg", "фото 1")

        assert dl._download_file.await_count == td.SIGNATURE_ATTEMPTS

    @pytest.mark.asyncio
    async def test_the_refreshed_url_is_taken_from_the_same_position(self):
        """A slideshow refresh must not shuffle which photo is which."""
        dl = self._downloader([_payload(images=["a0", "a1", "a2"]),
                               _payload(images=["b0", "b1", "b2"])])
        tried = []

        async def download(url, filename):
            tried.append(url)
            if len(tried) == 1:
                raise _http_error(403)

        dl._download_file = AsyncMock(side_effect=download)
        await dl._download_signed(
            lambda d, i=1: d["data"]["images"][i], "/tmp/x.jpg", "фото 2")

        assert tried == ["a1", "b1"]

    @pytest.mark.asyncio
    async def test_a_shorter_refreshed_post_fails_clearly(self):
        """Better than an IndexError from somewhere deep in the loop."""
        dl = self._downloader([_payload(images=["a0", "a1"]),
                               _payload(images=["b0"])])
        dl._download_file = AsyncMock(side_effect=_http_error(403))

        def resolve(data, index=1):
            fresh = (data.get("data") or {}).get("images") or []
            if index >= len(fresh):
                raise ValueError("Слайдшоу изменилось во время загрузки.")
            return fresh[index]

        with pytest.raises(ValueError):
            await dl._download_signed(resolve, "/tmp/x.jpg", "фото 2")

    @pytest.mark.asyncio
    async def test_a_video_url_is_refreshed_the_same_way(self):
        """One signed URL means one chance to be unlucky, but the same bug."""
        dl = self._downloader([_payload(play="stale"), _payload(play="fresh")])
        tried = []

        async def download(url, filename):
            tried.append(url)
            if len(tried) == 1:
                raise _http_error(403)

        dl._download_file = AsyncMock(side_effect=download)
        await dl._download_signed(
            lambda d: d["data"]["play"], "/tmp/v.mp4", "видео")
        assert tried == ["stale", "fresh"]


class TestSlideshowSurvivesOneBadPhoto:
    """Fourteen photos out of fifteen beat an error message."""

    def _downloader(self, images, refuse_indexes):
        dl = td.TikTokDownloader("https://vt.tiktok.com/XXXX/")
        dl._fetch_data = AsyncMock(return_value=_payload(images=images))

        async def download(url, filename):
            if images.index(url) in refuse_indexes:
                raise _http_error(403)
            with open(filename, "wb") as f:
                f.write(b"jpeg")

        dl._download_file = AsyncMock(side_effect=download)
        return dl

    @pytest.mark.asyncio
    async def test_a_clean_post_downloads_everything(self, tmp_path):
        dl = self._downloader(["a", "b", "c"], set())
        paths = await dl.download_slideshow(str(tmp_path))
        assert len(paths) == 3
        assert dl.skipped_images == 0

    @pytest.mark.asyncio
    async def test_a_refused_photo_is_skipped_not_fatal(self, tmp_path):
        dl = self._downloader(["a", "b", "c"], {1})
        paths = await dl.download_slideshow(str(tmp_path))
        assert len(paths) == 2
        assert dl.skipped_images == 1

    @pytest.mark.asyncio
    async def test_the_surviving_photos_keep_their_order(self, tmp_path):
        dl = self._downloader(["a", "b", "c", "d"], {1})
        paths = await dl.download_slideshow(str(tmp_path))
        assert [p.rsplit("_", 1)[-1] for p in paths] == ["0.jpg", "2.jpg", "3.jpg"]

    @pytest.mark.asyncio
    async def test_a_post_that_gives_up_nothing_is_still_an_error(self, tmp_path):
        """Delivering an empty album would be worse than saying so."""
        dl = self._downloader(["a", "b"], {0, 1})
        with pytest.raises(ValueError):
            await dl.download_slideshow(str(tmp_path))

    @pytest.mark.asyncio
    async def test_a_404_is_not_quietly_skipped(self, tmp_path):
        """Only a refused signature is survivable; a missing file is a bug."""
        dl = td.TikTokDownloader("https://vt.tiktok.com/XXXX/")
        dl._fetch_data = AsyncMock(return_value=_payload(images=["a", "b"]))
        dl._download_file = AsyncMock(side_effect=_http_error(404))
        with pytest.raises(aiohttp.ClientResponseError):
            await dl.download_slideshow(str(tmp_path))

    @pytest.mark.asyncio
    async def test_the_counter_resets_between_posts(self, tmp_path):
        dl = self._downloader(["a", "b"], {0})
        await dl.download_slideshow(str(tmp_path / "one"))
        assert dl.skipped_images == 1
        dl._download_file = AsyncMock(
            side_effect=lambda u, f: open(f, "wb").write(b"jpeg"))
        await dl.download_slideshow(str(tmp_path / "two"))
        assert dl.skipped_images == 0
