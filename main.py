import asyncio
import logging
import os
from dotenv import load_dotenv

asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from handlers import youtube
from handlers.youtube import register as register_youtube
from handlers.instagram import register as register_instagram
from handlers.twitter import register as register_twitter
from handlers.tiktok import TikTokHandler
from services.database import BotDatabase
from services.utils.env import resolve_admin_id
from services.utils.broadcast import broadcast_message
from services.utils.version import get_version

load_dotenv()

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    handlers=[
        RotatingFileHandler(
            os.path.join(LOG_DIR, "bot.log"),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)

app = Client(
    "tiktok_bot",
    api_id=int(os.getenv("API_KEY")),
    api_hash=os.getenv("API_HASH"),
    bot_token=os.getenv("BOT_TOKEN")
)

db = BotDatabase()

youtube.app = app  # pass client to handler

ADMIN_ID = resolve_admin_id()

@app.on_message(filters.command("start") & (filters.private | filters.group))
async def start_handler(client, message):
    # Register user in database
    if message.from_user:
        db.register_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
        )
    await message.reply(
        "Привет! Отправь ссылку на TikTok, YouTube, Instagram Reels или Twitter/X — и я помогу скачать видео.\n\n"
        "Можно кинуть сразу несколько ссылок в одном сообщении (до 5 штук), "
        "а ссылку на YouTube-плейлист — и я предложу скачать видео по очереди."
    )

@app.on_message(filters.command("version") & (filters.group | filters.private))
async def version_handler(client, message):
    await message.reply(f"🤖 Версия бота: v{get_version()}")

@app.on_message(filters.command("stats") & (filters.private | filters.group))
async def stats_handler(client, message):
    user_id = message.from_user.id if message.from_user else None
    if not user_id or user_id != ADMIN_ID:
        await message.reply("⛔ Нет доступа.")
        return

    stats = db.get_stats()
    tiktok_count = stats["by_platform"].get("tiktok", 0)
    youtube_count = stats["by_platform"].get("youtube", 0)
    instagram_count = stats["by_platform"].get("instagram", 0)
    twitter_count = stats["by_platform"].get("twitter", 0)
    first_seen = stats["first_seen"] or "—"

    downloads_24h = stats.get("downloads_24h_by_platform", {})
    errors_24h = stats.get("errors_24h_by_platform", {})

    def error_rate_line(platform_key: str, label: str) -> str:
        ok = downloads_24h.get(platform_key, 0)
        err = errors_24h.get(platform_key, 0)
        attempts = ok + err
        if attempts == 0:
            return f"{label}: нет попыток"
        return f"{label}: {err} ({round(err / attempts * 100)}%)"

    text = (
        f"📊 **Статистика бота** · v{get_version()}\n\n"
        f"👤 Пользователей: **{stats['total_users']}**\n"
        f"📥 Всего скачиваний: **{stats['total_downloads']}**\n"
        f"   ├ TikTok: {tiktok_count}\n"
        f"   ├ YouTube: {youtube_count}\n"
        f"   ├ Instagram: {instagram_count}\n"
        f"   └ Twitter/X: {twitter_count}\n"
        f"🕐 Активных за 24ч: **{stats['active_24h']}**\n"
        f"📅 Бот работает с: {first_seen}\n\n"
        f"⚠️ Ошибки за 24ч:\n"
        f"   ├ {error_rate_line('tiktok', 'TikTok')}\n"
        f"   ├ {error_rate_line('youtube', 'YouTube')}\n"
        f"   ├ {error_rate_line('instagram', 'Instagram')}\n"
        f"   └ {error_rate_line('twitter', 'Twitter/X')}"
    )
    await message.reply(text)

@app.on_message(filters.command("broadcast") & (filters.private | filters.group))
async def broadcast_handler(client, message):
    user_id = message.from_user.id if message.from_user else None
    if not user_id or user_id != ADMIN_ID:
        await message.reply("⛔ Нет доступа.")
        return

    parts = message.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply("Использование: /broadcast <текст сообщения>")
        return

    broadcast_text = parts[1].strip()
    user_ids = db.get_broadcast_subscribed_user_ids()

    status_msg = await message.reply(f"📣 Рассылаю {len(user_ids)} пользователям...")

    unsub_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔕 Больше не присылать рассылки", callback_data="broadcast_unsub")
    ]])
    results = await broadcast_message(client, user_ids, broadcast_text, reply_markup=unsub_markup)

    names = db.get_user_display_names(user_ids)
    sent_ids = [uid for uid, ok, _ in results if ok]
    failed_ids = [uid for uid, ok, _ in results if not ok]

    lines = [
        "📣 Рассылка завершена.",
        f"✅ Отправлено: {len(sent_ids)}",
        f"❌ Не удалось: {len(failed_ids)}",
    ]
    if sent_ids:
        lines.append("\n✅ Получили: " + ", ".join(names.get(uid, str(uid)) for uid in sent_ids))
    if failed_ids:
        lines.append("\n❌ Не получили: " + ", ".join(names.get(uid, str(uid)) for uid in failed_ids))

    await status_msg.edit_text("\n".join(lines))

@app.on_callback_query(filters.regex(r'^broadcast_unsub$'))
async def broadcast_unsub_handler(client, callback):
    if callback.from_user:
        db.set_broadcast_opt_out(callback.from_user.id, True)
    await callback.answer("Вы отписались от рассылок. Скачивание видео продолжит работать как обычно.", show_alert=True)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

if __name__ == "__main__":
    # Abandoned picker tokens and playlist sessions are never cleaned up on
    # their own, so sweep the stale ones on every start.
    removed = db.cleanup_stale_state()
    if removed["callbacks"] or removed["playlist_state"]:
        print(f"🧹 Removed stale rows: {removed}")

    register_youtube(app, db)
    register_instagram(app, db)
    register_twitter(app, db)
    TikTokHandler(app, db).register()
    print("🚀 Bot started!")

    try:
        app.run()
    finally:
        db.close()
        print("💾 Database connection closed cleanly.")