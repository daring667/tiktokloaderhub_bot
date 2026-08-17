from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.enums import ChatMemberStatus

from handlers import all_mention
from _helpers import FakeApp, make_message


def make_member(user_id, name, *, bot=False, deleted=False, status=ChatMemberStatus.MEMBER):
    user = SimpleNamespace(id=user_id, first_name=name, username=None, is_bot=bot, is_deleted=deleted)
    return SimpleNamespace(user=user, status=status)


class Client:
    def __init__(self, members, status=ChatMemberStatus.ADMINISTRATOR):
        self._members = members
        self._status = status

    async def get_chat_member(self, _chat_id, _user_id):
        return SimpleNamespace(status=self._status)

    async def get_chat_members(self, _chat_id):
        for member in self._members:
            yield member


@pytest.fixture(autouse=True)
def clear_cooldown():
    all_mention._last_mention_at.clear()


#@pytest.mark.asyncio
#async def test_admin_all_replies_with_real_mentions_and_text():
#    app = FakeApp()
#   all_mention.register(app)
 #   handler = app.message_handlers[0]
  #  message = make_message("@all Собираемся через пять минут", user_id=1, chat_id=-100)
   # client = Client([make_member(1, "Admin"), make_member(2, "Alice"), make_member(3, "Bob")])
#
 #   await handler(client, message)
#
 #   text = message.reply.await_args.args[0]
  #  assert "Собираемся через пять минут" in text
   # assert 'tg://user?id=2' in text
    #assert 'tg://user?id=3' in text
    #assert 'tg://user?id=1' not in text


#@pytest.mark.asyncio
#async def test_non_admin_cannot_mention_everyone():
#    app = FakeApp()
#    all_mention.register(app)
#    handler = app.message_handlers[0]
#    message = make_message("@all привет", chat_id=-100)
#    client = Client([], status=ChatMemberStatus.MEMBER)
#
#    await handler(client, message)
#
#    assert "только администратор" in message.reply.await_args.args[0]


#@pytest.mark.asyncio
#async def test_bots_and_deleted_accounts_are_not_mentioned():
 #   app = FakeApp()
  #  all_mention.register(app)
  #  handler = app.message_handlers[0]
  #  message = make_message("@all", user_id=1, chat_id=-100)
  #  client = Client([
  #      make_member(1, "Admin"), make_member(2, "Alice"),
  #      make_member(3, "Helper", bot=True), make_member(4, "Deleted", deleted=True),
  #  ])
#
#    await handler(client, message)
#
#    text = message.reply.await_args.args[0]
#    assert 'id=2' in text
#    assert 'id=3' not in text
#   assert 'id=4' not in text
#