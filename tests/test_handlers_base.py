"""Tests for the shared handler helpers in handlers/base.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.base import download_slot, DownloadInProgress, safe_delete, cleanup_files, user_key_for
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
