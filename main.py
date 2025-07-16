import os
import time
import re
import requests
from dotenv import load_dotenv
from pyrogram import Client, filters
import asyncio

load_dotenv()

API_ID = int(os.getenv("API_KEY"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))  # твой Telegram user ID

app = Client("tiktok_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
downloading_users = set()


async def send_log(text: str):
    try:
        await app.send_message(chat_id=OWNER_ID, text=f"🛠️ {text}")
    except Exception as e:
        print(f"❌ Не смог отправить лог: {e}")


@app.on_message(filters.regex(r'(https?://)?(www\.)?tiktok\.com/[^\s]+') & (filters.group | filters.private))
async def download_tiktok(client, message):
    user_id = message.from_user.id
    text = message.text or message.caption or ""
    await send_log(f"📥 Ссылка от {user_id}: {text[:50]}")

    if user_id in downloading_users:
        await message.reply("⏳ Подожди, пока закончится предыдущая загрузка.")
        return

    downloading_users.add(user_id)
    msg = await message.reply("⏳")
    filename = None

    try:
        match = re.search(r'https?://\S+', text)
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
            await send_log("❌ Ошибка: TikWM вернул невалидный JSON")
            return

        video_url = data.get("data", {}).get("play")
        if not video_url:
            error_message = data.get("msg", "Видео недоступно.")
            await msg.edit(f"❌ Ошибка: {error_message}")
            await send_log(f"⚠️ Видео не найдено. TikWM сказал: {error_message}")
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
        await send_log(f"✅ Видео отправлено юзеру: {user_id}")

    except Exception as e:
        await msg.edit(f"❌ Не получилось: {e}")
        await send_log(f"💥 Ошибка при загрузке: {e}")

    finally:
        downloading_users.discard(user_id)
        if filename and os.path.exists(filename):
            os.remove(filename)




async def main():
    print("🚀 Запускаем Telegram бот...")
    await app.start()
    await send_log("🚀 Бот запущен и готов к работе!")

    try:
        await asyncio.Event().wait()  # бот работает бесконечно
    finally:
        await send_log("🛑 Бот остановлен.")
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
