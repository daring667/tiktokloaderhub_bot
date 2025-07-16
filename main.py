import os
import time
import re
import requests
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

API_ID = int(os.getenv("API_KEY"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_URL = os.getenv("BOT_URL", "tiktokbot")
CHANNEL_URL = os.getenv("CHANNEL_URL", "")

app = Client("tiktok_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@app.on_message(filters.command("start") & (filters.private | filters.group))
async def start_cmd(client, message):
    keyboard = []
    if CHANNEL_URL:
        keyboard.append([InlineKeyboardButton("📢 Канал", url=CHANNEL_URL)])
    keyboard.append([InlineKeyboardButton("🔗 Автор", url="https://t.me/ID_Darling")])

    await message.reply(
        "👋 Привет! Я бот для скачивания видео из TikTok без водяного знака.\n"
        "Просто отправь ссылку на видео TikTok в этот чат.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


@app.on_message(filters.regex(r'https?://') & (filters.group | filters.private))
async def download_tiktok(client, message):
    msg = await message.reply("⏳")
    filename = None

    try:
        match = re.search(r'https?://\S+', message.text or "")
        if not match:
            await msg.edit("❌ Не могу найти ссылку.")
            return

        url = match.group(0)
        api = "https://tikwm.com/api/"
        res = requests.get(api, params={"url": url}, timeout=10)

        try:
            data = res.json()
        except Exception:
            await msg.edit("❌ TikWM API вернул неверный ответ.")
            return

        video_url = data.get("data", {}).get("play")
        if not video_url:
            error_message = data.get("msg", "Видео недоступно.")
            await msg.edit(f"❌ Ошибка: {error_message}")
            return

        filename = f"{int(time.time())}.mp4"
        with requests.get(video_url, stream=True) as r:
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

        await message.delete()  # 🧹 Удаляем сообщение с ссылкой
        await client.send_video(message.chat.id, video=filename)
        await msg.delete()

    except Exception as e:
        await msg.edit(f"❌ Не получилось: {e}")

    finally:
        if filename and os.path.exists(filename):
            os.remove(filename)


if __name__ == "__main__":
    app.run()
