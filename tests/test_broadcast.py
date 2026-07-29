"""Tests for services/utils/broadcast.py (admin /broadcast helper)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from services.utils.broadcast import broadcast_message


class TestBroadcastMessage:
    @pytest.mark.asyncio
    async def test_sends_to_every_user(self):
        client = MagicMock()
        client.send_message = AsyncMock()

        sent, failed = await broadcast_message(client, [1, 2, 3], "hello", delay=0)

        assert sent == 3
        assert failed == 0
        assert client.send_message.await_count == 3

    @pytest.mark.asyncio
    async def test_continues_past_individual_failures(self):
        client = MagicMock()
        client.send_message = AsyncMock(side_effect=[None, Exception("blocked"), None])

        sent, failed = await broadcast_message(client, [1, 2, 3], "hello", delay=0)

        assert sent == 2
        assert failed == 1
        assert client.send_message.await_count == 3

    @pytest.mark.asyncio
    async def test_empty_user_list(self):
        client = MagicMock()
        client.send_message = AsyncMock()

        sent, failed = await broadcast_message(client, [], "hello", delay=0)

        assert (sent, failed) == (0, 0)
        client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_correct_text_and_recipient(self):
        client = MagicMock()
        client.send_message = AsyncMock()

        await broadcast_message(client, [42], "important update", delay=0)

        client.send_message.assert_awaited_once_with(42, "important update")
