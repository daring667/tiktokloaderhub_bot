"""Shared test doubles for handler tests. Not a pytest test module itself."""
from unittest.mock import MagicMock, AsyncMock


class FakeApp:
    """Captures handlers registered via on_message/on_callback_query,
    standing in for pyrogram.Client in handler unit tests."""

    def __init__(self):
        self.message_handlers = []
        self.callback_handlers = []

    def on_message(self, _filter):
        def decorator(func):
            self.message_handlers.append(func)
            return func
        return decorator

    def on_callback_query(self, _filter):
        def decorator(func):
            self.callback_handlers.append(func)
            return func
        return decorator


def make_message(text, user_id=111, username="user", first_name="Test", chat_id=111):
    """A MagicMock standing in for pyrogram.types.Message."""
    message = MagicMock()
    message.text = text
    message.from_user = MagicMock(id=user_id, username=username, first_name=first_name)
    message.chat = MagicMock(id=chat_id)

    reply_msg = MagicMock()
    reply_msg.edit = AsyncMock()
    reply_msg.edit_text = AsyncMock()
    reply_msg.delete = AsyncMock()

    message.reply = AsyncMock(return_value=reply_msg)
    message.delete = AsyncMock()
    return message


def make_client():
    client = MagicMock()
    client.send_video = AsyncMock()
    client.send_audio = AsyncMock()
    return client


def make_callback(data, user_id=111):
    callback = MagicMock()
    callback.data = data
    callback.from_user = MagicMock(id=user_id)
    callback.answer = AsyncMock()
    callback.message = make_message("")
    return callback
