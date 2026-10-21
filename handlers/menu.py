"""The bot's button surface: a persistent menu and the settings behind it.

Everything used to go through typed slash commands with no buttons at all,
which is what made the bot feel unusable. The reply keyboard below stays on
screen, so the two things people actually reach for -- the Mini App and their
own preferences -- are one tap away, and the chat stays free for links.

Settings live on an inline keyboard that edits itself in place rather than
posting a new message per tap, so changing three options leaves one message
behind instead of six.
"""
import logging

from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from services import user_settings as us
from services.utils.env import get_miniapp_url

BTN_APP = "📥 Mini App"
BTN_SETTINGS = "⚙️ Настройки"
BTN_HELP = "❓ Помощь"

# Callback payloads are capped at 64 bytes, so keep the prefix short.
CB = "cfg"

HELP_TEXT = (
    "<b>Как пользоваться</b>\n\n"
    "Пришли ссылку на видео — я скачаю и отправлю его сюда.\n"
    "Работает с TikTok, YouTube, Instagram Reels и Twitter/X.\n\n"
    "• Можно прислать до 5 ссылок в одном сообщении\n"
    "• Ссылка на плейлист YouTube — предложу скачать по очереди\n"
    "• Фото-слайдшоу из TikTok придут альбомом\n\n"
    "Telegram не разрешает ботам отправлять файлы тяжелее 50 МБ, "
    "поэтому для длинных роликов я подбираю качество под этот предел.\n\n"
    f"Что присылать по умолчанию — настраивается в «{BTN_SETTINGS}».\n\n"
    "Что-то не работает? Команда /report — опишешь проблему, "
    "и я отвечу тебе прямо здесь."
)


def main_keyboard() -> ReplyKeyboardMarkup:
    """The menu that stays on screen.

    The Mini App sits on a `web_app` button so it opens on the first tap
    instead of costing a round trip through the bot.
    """
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(BTN_APP, web_app=WebAppInfo(url=get_miniapp_url())),
                KeyboardButton(BTN_SETTINGS),
            ],
            [KeyboardButton(BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        placeholder="Пришли ссылку на видео",
    )


def overview_text(settings: dict) -> str:
    current = us.normalize(settings)
    lines = ["<b>⚙️ Настройки</b>", ""]
    for key in ("quality", "audio", "groups"):
        lines.append(f"<b>{us.TITLES[key]}</b>\n{us.label_for(key, current[key])}")
        lines.append("")
    lines.append("Выбери, что изменить.")
    return "\n".join(lines)


def overview_markup() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(us.TITLES[key], callback_data=f"{CB}|open|{key}")]
        for key in ("quality", "audio", "groups")
    ]
    rows.append([InlineKeyboardButton("↩️ Сбросить", callback_data=f"{CB}|reset")])
    return InlineKeyboardMarkup(rows)


def option_text(key: str) -> str:
    return f"<b>{us.TITLES[key]}</b>\n\n{us.HINTS[key]}"


def option_markup(key: str, current: str) -> InlineKeyboardMarkup:
    rows = []
    for value, label in us.OPTIONS[key]:
        mark = "✅ " if value == current else ""
        rows.append([InlineKeyboardButton(
            f"{mark}{label}", callback_data=f"{CB}|set|{key}|{value}")])
    rows.append([InlineKeyboardButton("← Назад", callback_data=f"{CB}|back")])
    return InlineKeyboardMarkup(rows)


async def _edit(callback, text, markup):
    """Edit in place, tolerating Telegram's "message is not modified".

    Tapping the option that is already selected is a no-op for Telegram but
    an exception for us, and it should not look like a failure to the user.
    """
    try:
        await callback.message.edit_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e).upper():
            logging.warning("settings edit failed: %s", e)


def register(app, db):

    async def _send_settings(message):
        settings = db.get_user_settings(message.from_user.id) if message.from_user else {}
        await message.reply(
            overview_text(settings),
            reply_markup=overview_markup(),
            parse_mode=ParseMode.HTML,
        )

    # Both the keyboard button and the command menu reach the same screen:
    # whichever the person reaches for, the bot behaves the same way.
    @app.on_message(filters.private & filters.text & filters.regex(f"^{BTN_SETTINGS}$"))
    async def open_settings_button(client, message):
        await _send_settings(message)

    @app.on_message(filters.command("settings") & filters.private)
    async def open_settings_command(client, message):
        await _send_settings(message)

    @app.on_message(filters.private & filters.text & filters.regex(f"^{BTN_HELP}$"))
    async def show_help_button(client, message):
        await message.reply(HELP_TEXT, parse_mode=ParseMode.HTML)

    @app.on_message(filters.command("help") & (filters.private | filters.group))
    async def show_help_command(client, message):
        await message.reply(HELP_TEXT, parse_mode=ParseMode.HTML)

    @app.on_callback_query(filters.regex(f"^{CB}\\|"))
    async def on_settings_callback(client, callback):
        user_id = callback.from_user.id if callback.from_user else None
        if not user_id:
            await callback.answer()
            return

        parts = callback.data.split("|")
        action = parts[1] if len(parts) > 1 else ""

        if action == "open" and len(parts) > 2 and parts[2] in us.DEFAULTS:
            key = parts[2]
            current = us.normalize(db.get_user_settings(user_id))[key]
            await _edit(callback, option_text(key), option_markup(key, current))
            await callback.answer()
            return

        if action == "set" and len(parts) > 3:
            key, value = parts[2], parts[3]
            # Never trust the payload: a callback can be replayed with an
            # edited key or value long after the option stopped existing.
            if key not in us.DEFAULTS or value not in us.valid_values(key):
                await callback.answer("Эта настройка больше не доступна.", show_alert=True)
                return
            db.set_user_setting(user_id, key, value)
            await _edit(callback, option_text(key), option_markup(key, value))
            await callback.answer(f"{us.TITLES[key]}: {us.label_for(key, value)}")
            return

        if action == "reset":
            db.reset_user_settings(user_id)
            await _edit(callback, overview_text({}), overview_markup())
            await callback.answer("Вернул настройки по умолчанию.")
            return

        # "back", and anything unrecognised, returns to the overview rather
        # than leaving the user on a dead screen.
        await _edit(callback, overview_text(db.get_user_settings(user_id)),
                    overview_markup())
        await callback.answer()
