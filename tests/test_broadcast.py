"""Tests for services/utils/broadcast.py (admin /broadcast helper)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from services.utils.broadcast import broadcast_message


class TestBroadcastMessage:
    @pytest.mark.asyncio
    async def test_sends_to_every_user(self):
        client = MagicMock()
        client.send_message = AsyncMock()

        results = await broadcast_message(client, [1, 2, 3], "hello", delay=0)

        assert [uid for uid, ok, _ in results] == [1, 2, 3]
        assert all(ok for _, ok, _ in results)
        assert client.send_message.await_count == 3

    @pytest.mark.asyncio
    async def test_continues_past_individual_failures(self):
        client = MagicMock()
        client.send_message = AsyncMock(side_effect=[None, Exception("blocked"), None])

        results = await broadcast_message(client, [1, 2, 3], "hello", delay=0)

        assert results[0] == (1, True, None)
        assert results[1][0] == 2 and results[1][1] is False and "blocked" in results[1][2]
        assert results[2] == (3, True, None)
        assert client.send_message.await_count == 3

    @pytest.mark.asyncio
    async def test_empty_user_list(self):
        client = MagicMock()
        client.send_message = AsyncMock()

        results = await broadcast_message(client, [], "hello", delay=0)

        assert results == []
        client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_correct_text_and_recipient(self):
        client = MagicMock()
        client.send_message = AsyncMock()

        await broadcast_message(client, [42], "important update", delay=0)

        client.send_message.assert_awaited_once_with(42, "important update", reply_markup=None)

    @pytest.mark.asyncio
    async def test_passes_reply_markup_through(self):
        client = MagicMock()
        client.send_message = AsyncMock()
        markup = MagicMock(name="markup")

        await broadcast_message(client, [42], "hi", delay=0, reply_markup=markup)

        client.send_message.assert_awaited_once_with(42, "hi", reply_markup=markup)
