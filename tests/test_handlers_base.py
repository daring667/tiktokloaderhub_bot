"""Tests for the shared handler helpers in handlers/base.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.base import (
    download_slot,
    DownloadInProgress,
    RateLimited,
    rate_limit_message,
    safe_delete,
    cleanup_files,
    user_key_for,
    report_error,
    extract_platform_urls,
    MAX_LINKS_PER_MESSAGE,
)
from _helpers import make_message


class TestDownloadSlot:
    @pytest.mark.asyncio
    async def test_blocks_concurrent_same_key(self):
        active = set()
        async with download_slot(active, "user1"):
            assert "user1" in active
            with pytest.raises(DownloadInProgress):
                async with download_slot(active, "user1"):
                    pass

    @pytest.mark.asyncio
    async def test_releases_key_after_block(self):
        active = set()
        async with download_slot(active, "user1"):
            pass
        assert "user1" not in active

    @pytest.mark.asyncio
    async def test_releases_key_on_exception(self):
        active = set()
        with pytest.raises(ValueError):
            async with download_slot(active, "user1"):
                raise ValueError("boom")
        assert "user1" not in active

    @pytest.mark.asyncio
    async def test_rate_limited_immediately_after_finishing(self, monkeypatch):
        import handlers.base as base
        monkeypatch.setattr(base, "REQUEST_COOLDOWN_SECONDS", 100)
        active = set()

        async with download_slot(active, "user1"):
            pass  # first request completes normally, starting the cooldown

        with pytest.raises(RateLimited) as exc_info:
            async with download_slot(active, "user1"):
                pass
        assert exc_info.value.retry_after > 0

    @pytest.mark.asyncio
    async def test_allowed_again_once_cooldown_elapses(self, monkeypatch):
        import handlers.base as base
        monkeypatch.setattr(base, "REQUEST_COOLDOWN_SECONDS", 100)
        active = set()

        async with download_slot(active, "user1"):
            pass

        base._last_finished_at["user1"] -= 101  # simulate time passing

        async with download_slot(active, "user1"):
            pass  # must not raise

    @pytest.mark.asyncio
    async def test_rate_limit_is_per_key(self, monkeypatch):
        import handlers.base as base
        monkeypatch.setattr(base, "REQUEST_COOLDOWN_SECONDS", 100)
        active = set()

        async with download_slot(active, "user1"):
            pass

        async with download_slot(active, "user2"):
            pass  # different user — must not raise

    @pytest.mark.asyncio
    async def test_zero_cooldown_never_rate_limits(self, monkeypatch):
        import handlers.base as base
        monkeypatch.setattr(base, "REQUEST_COOLDOWN_SECONDS", 0)
        active = set()

        async with download_slot(active, "user1"):
            pass
        async with download_slot(active, "user1"):
            pass  # must not raise

    def test_rate_limit_message_rounds_up(self):
        assert rate_limit_message(RateLimited(2.1)) == "⏳ Подожди ещё 3 сек. перед следующей ссылкой."

    @pytest.mark.asyncio
    async def test_different_keys_dont_block_each_other(self):
        active = set()
        async with download_slot(active, "user1"):
            async with download_slot(active, "user2"):
                assert active == {"user1", "user2"}


class TestSafeDelete:
    @pytest.mark.asyncio
    async def test_calls_delete(self):
        msg = MagicMock()
        msg.delete = AsyncMock()
        await safe_delete(msg)
        msg.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_exception(self):
        msg = MagicMock()
        msg.delete = AsyncMock(side_effect=Exception("no perms"))
        await safe_delete(msg)  # must not raise

    @pytest.mark.asyncio
    async def test_none_is_noop(self):
        await safe_delete(None)  # must not raise


class TestCleanupFiles:
    def test_removes_existing_files(self, tmp_path):
        f1 = tmp_path / "a.mp4"
        f2 = tmp_path / "b.mp4"
        f1.write_bytes(b"x")
        f2.write_bytes(b"y")

        cleanup_files(str(f1), str(f2))

        assert not f1.exists()
        assert not f2.exists()

    def test_ignores_missing_and_none(self, tmp_path):
        missing = str(tmp_path / "nope.mp4")
        cleanup_files(missing, None, "")  # must not raise


class TestUserKeyFor:
    def test_uses_user_id_when_present(self):
        msg = make_message("hi", user_id=42)
        assert user_key_for(msg) == 42

    def test_falls_back_to_chat_id(self):
        msg = make_message("hi", chat_id=111)
        msg.from_user = None
        assert user_key_for(msg) == "chat:111"


class TestReportError:
    @pytest.mark.asyncio
    async def test_noop_when_no_admin_configured(self, monkeypatch):
        monkeypatch.delenv("ADMIN_ID", raising=False)
        monkeypatch.delenv("OWNER_ID", raising=False)
        client = MagicMock()
        client.send_message = AsyncMock()

        await report_error(client, "tiktok", "https://tiktok.com/x", None, ValueError("boom"))

        client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_message_to_admin_when_configured(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ID", "999")
        client = MagicMock()
        client.send_message = AsyncMock()
        user = MagicMock(id=42, username="bob")

        await report_error(client, "youtube", "https://youtu.be/x", user, ValueError("parse failed"))

        client.send_message.assert_awaited_once()
        args, kwargs = client.send_message.await_args
        assert args[0] == 999
        assert "youtube" in args[1]
        assert "@bob" in args[1]
        assert "parse failed" in args[1]

    @pytest.mark.asyncio
    async def test_falls_back_to_owner_id(self, monkeypatch):
        monkeypatch.delenv("ADMIN_ID", raising=False)
        monkeypatch.setenv("OWNER_ID", "777")
        client = MagicMock()
        client.send_message = AsyncMock()

        await report_error(client, "instagram", "https://instagram.com/reel/x", None, ValueError("boom"))

        assert client.send_message.await_args.args[0] == 777

    @pytest.mark.asyncio
    async def test_never_raises_when_send_message_fails(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ID", "999")
        client = MagicMock()
        client.send_message = AsyncMock(side_effect=Exception("network down"))

        await report_error(client, "tiktok", "https://tiktok.com/x", None, ValueError("boom"))  # must not raise

    @pytest.mark.asyncio
    async def test_escapes_html_in_error_text(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ID", "999")
        client = MagicMock()
        client.send_message = AsyncMock()

        await report_error(client, "tiktok", "https://tiktok.com/x", None, ValueError("<script>bad</script>"))

        text = client.send_message.await_args.args[1]
        assert "<script>" not in text
        assert "&lt;script&gt;" in text

    @pytest.mark.asyncio
    async def test_logs_to_db_even_without_admin(self, monkeypatch):
        monkeypatch.delenv("ADMIN_ID", raising=False)
        monkeypatch.delenv("OWNER_ID", raising=False)
        client = MagicMock()
        client.send_message = AsyncMock()
        db = MagicMock()

        await report_error(client, "tiktok", "https://tiktok.com/x", None, ValueError("boom"), db)

        db.log_error.assert_called_once_with("tiktok", "ValueError", "boom")
        client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_logging_failure_does_not_block_alert(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ID", "999")
        client = MagicMock()
        client.send_message = AsyncMock()
        db = MagicMock()
        db.log_error.side_effect = Exception("db locked")

        await report_error(client, "tiktok", "https://tiktok.com/x", None, ValueError("boom"), db)

        client.send_message.assert_awaited_once()  # must not have been skipped

    @pytest.mark.asyncio
    async def test_repeat_errors_are_throttled(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ID", "999")
        client = MagicMock()
        client.send_message = AsyncMock()

        await report_error(client, "tiktok", "url1", None, ValueError("first"))
        await report_error(client, "tiktok", "url2", None, ValueError("second"))
        await report_error(client, "tiktok", "url3", None, ValueError("third"))

        client.send_message.assert_awaited_once()  # only the first got through

    @pytest.mark.asyncio
    async def test_next_alert_after_cooldown_reports_suppressed_count(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ID", "999")
        client = MagicMock()
        client.send_message = AsyncMock()

        await report_error(client, "tiktok", "url1", None, ValueError("first"))
        await report_error(client, "tiktok", "url2", None, ValueError("second"))  # suppressed

        import handlers.base as base
        # simulate the cooldown having elapsed
        key = ("tiktok", "ValueError")
        base._error_alert_state[key]["last_sent"] -= base.ERROR_REPORT_COOLDOWN + 1

        await report_error(client, "tiktok", "url3", None, ValueError("third"))

        assert client.send_message.await_count == 2
        second_text = client.send_message.await_args.args[1]
        assert "+1" in second_text

    @pytest.mark.asyncio
    async def test_different_platforms_dont_throttle_each_other(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ID", "999")
        client = MagicMock()
        client.send_message = AsyncMock()

        await report_error(client, "tiktok", "url1", None, ValueError("first"))
        await report_error(client, "youtube", "url2", None, ValueError("first"))

        assert client.send_message.await_count == 2


class TestExtractPlatformUrls:
    @staticmethod
    def _is_tiktok(url):
        return "tiktok.com" in url

    def test_filters_to_matching_platform_only(self):
        text = "https://www.tiktok.com/@a/video/1 https://youtu.be/xyz https://vm.tiktok.com/b"
        urls, total = extract_platform_urls(text, self._is_tiktok)
        assert urls == ["https://www.tiktok.com/@a/video/1", "https://vm.tiktok.com/b"]
        assert total == 2

    def test_no_matches_returns_empty(self):
        urls, total = extract_platform_urls("https://youtu.be/xyz", self._is_tiktok)
        assert urls == []
        assert total == 0

    def test_caps_at_max_links_and_reports_true_total(self):
        links = " ".join(f"https://tiktok.com/@u/video/{i}" for i in range(MAX_LINKS_PER_MESSAGE + 3))
        urls, total = extract_platform_urls(links, self._is_tiktok)
        assert len(urls) == MAX_LINKS_PER_MESSAGE
        assert total == MAX_LINKS_PER_MESSAGE + 3

    def test_empty_text(self):
        urls, total = extract_platform_urls("", self._is_tiktok)
        assert urls == []
        assert total == 0
