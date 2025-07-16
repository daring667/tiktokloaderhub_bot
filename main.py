import os
import time
import re
import requests
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio

load_dotenv()

API_ID = int(os.getenv("API_KEY"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_URL = os.getenv("BOT_URL", "tiktokbot")
CHANNEL_URL = os.getenv("CHANNEL_URL", "")
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "-1001234567890"))

downloading_users = set()
app = Client("tiktok_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.text)
async def catch_chat_id(client, message):
    print(f"chat_id: {message.chat.id}")
async def send_log(text: str):
    try:
        await app.send_message(LOG_CHAT_ID, f"📘 {text}")
    except Exception as e:
        print(f"Не смог отправить лог: {e}")


@app.on_message(filters.regex(r'(https?://)?([a-z]+\.)?tiktok\.com/[^\s]+') & (filters.group | filters.private))
async def download_tiktok(client, message):
    await send_log(f"📥 Получена ссылка от {message.from_user.id}")
    user_id = message.from_user.id
    if user_id in downloading_users:
        await message.reply("⏳ Подожди, пока закончится предыдущая загрузка.")
        return

    downloading_users.add(user_id)
    msg = await message.reply("⏳")
    filename = None

    try:
        match = re.search(r'https?://\S+', message.text or "")
        if not match:
            await msg.edit("❌ Не могу найти ссылку.")
            return

        url = match.group(0)
        api = "https://tikwm.com/api/"
        await asyncio.sleep(1.1)
        res = requests.get(api, params={"url": url}, timeout=10)

        try:
            data = res.json()
        except Exception:
            await msg.edit("❌ TikWM API вернул неверный ответ.")
            await send_log("❌ Ошибка парсинга JSON из API")
            return

        video_url = data.get("data", {}).get("play")
        if not video_url:
            error_message = data.get("msg", "Видео недоступно.")
            await msg.edit(f"❌ Ошибка: {error_message}")
            await send_log(f"⚠️ Ошибка TikWM: {error_message}")
            return

        filename = f"{int(time.time())}.mp4"
        with requests.get(video_url, stream=True) as r:
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

        await message.delete()
        await client.send_video(message.chat.id, video=filename)
        await msg.delete()
        await send_log(f"✅ Успешно отправлено видео для {user_id}")

    except Exception as e:
        await msg.edit(f"❌ Не получилось: {e}")
        await send_log(f"❌ Ошибка загрузки: {e}")

    finally:
        downloading_users.discard(user_id)
        if filename and os.path.exists(filename):
            os.remove(filename)


@app.on_message(filters.chat(LOG_CHAT_ID) & filters.text)
async def debug_chat_id(client, message):
    print(message.chat.id)


async def main():
    print("🚀 Запускаем Telegram бот...")
    await app.start()
    await send_log("🚀 Бот был запущен!")

    try:
        # Поддерживаем процесс "живым"
        while await app.running():
            await asyncio.sleep(1)
    finally:
        await send_log("🛑 Бот остановлен!")
        await app.stop()



if __name__ == "__main__":
    print("🚀 Запускаем Telegram бот...")
    app.run()

