"""Group-only ``@all`` mentions for chat administrators.

Telegram has no native @all mention.  This handler turns a message containing
``@all`` into one or more replies with real user mentions, so members receive
their normal Telegram notification according to their own notification setup.
"""
import asyncio
import html
import re
import time

from pyrogram import filters

ALL_PATTERN = re.compile(r"(?<!\w)@all\b", re.IGNORECASE)
COOLDOWN_SECONDS = 60
MAX_MESSAGE_LENGTH = 3900
MAX_MENTIONS_PER_MESSAGE = 40

_last_mention_at: dict[int, float] = {}


def _mention(user) -> str:
    """Make an HTML mention that also works for people without a username."""
    label = user.first_name or user.username or "Участник"
    return f'<a href="tg://user?id={user.id}">{html.escape(label)}</a>'


def _chunks(items: list[str]):
    """Keep every reply below Telegram's text limit."""
    chunk: list[str] = []
    size = 0
    for item in items:
        extra = len(item) + (1 if chunk else 0)
        if chunk and (len(chunk) >= MAX_MENTIONS_PER_MESSAGE or size + extra > MAX_MESSAGE_LENGTH):
            yield chunk
            chunk = []
            size = 0
        chunk.append(item)
        size += len(item) + (1 if len(chunk) > 1 else 0)
    if chunk:
        yield chunk


def register(app):
    @app.on_message(filters.regex(ALL_PATTERN) & filters.group)
    async def all_mention_handler(client, message):
        if not message.from_user or not message.text:
            return

        now = time.monotonic()
        wait = COOLDOWN_SECONDS - (now - _last_mention_at.get(message.chat.id, 0))
        if wait > 0:
            await message.reply(f"⏳ @all можно использовать раз в минуту. Подожди ещё {int(wait) + 1} сек.")
            return

        mentions: list[str] = []
        try:
            async for member in client.get_chat_members(message.chat.id):
                user = member.user
                if user and not getattr(user, "is_bot", False) and not getattr(user, "is_deleted", False):
                    mentions.append(_mention(user))
        except Exception:
            await message.reply("❌ Не удалось получить список участников. Проверь, что бот состоит в чате.")
            return

        # Avoid including the author twice: their original @all message already
        # gives them the context and they don't need a notification from the bot.
        mentions = [item for item in mentions if f'id={message.from_user.id}"' not in item]
        if not mentions:
            await message.reply("ℹ️ Не нашёл участников, которых можно отметить.")
            return

        _last_mention_at[message.chat.id] = now
        body = ALL_PATTERN.sub("", message.text, count=1).strip()
        chunks = list(_chunks(mentions))
        for index, chunk in enumerate(chunks):
            prefix = "📣 " + html.escape(body) + "\n\n" if index == 0 and body else "📣 Внимание всем:\n\n"
            await message.reply(prefix + " ".join(chunk), disable_web_page_preview=True)
            # A small spacing avoids hitting Telegram's flood limit in large chats.
            if index < len(chunks) - 1:
                await asyncio.sleep(0.2)

    return all_mention_handler
