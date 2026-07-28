from pyrogram import filters
from services.tiktok.tiktok_downloader import TikTokDownloader
from services.downloader import extract_url
from handlers.base import (
    BaseHandler,
    DownloadInProgress,
    download_slot,
    safe_delete,
    cleanup_files,
    user_key_for,
)
import os, uuid, aiohttp, asyncio

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

active_downloads = set()

class TikTokHandler(BaseHandler):
    def __init__(self, app, db=None):
        super().__init__(app)
        self.db = db

    def register(self):
        db = self.db

        @self.app.on_message(filters.regex(r'https?://(www\.|vm\.|vt\.|m\.)?tiktok\.com/'))
        async def handle_tiktok(client, message):
            print(f"[TikTok] Received message from {message.from_user.id if message.from_user else 'unknown'}: {message.text}")

            url = extract_url(message.text or "")
            if not url:
                return await message.reply("❌ Не найдена ссылка.")

            try:
                async with download_slot(active_downloads, user_key_for(message)):
                    await _download_and_send(client, message, url, db)
            except DownloadInProgress:
                await message.reply("⏳ Подожди, идёт другая загрузка.")


async def _download_and_send(client, message, url, db):
    msg = await message.reply("⏳ Загружаю...")
    filename = os.path.join(DOWNLOADS_DIR, f"{uuid.uuid4()}.mp4")
    result_path = None

    try:
        # Небольшая пауза (может помочь от спама)
        await asyncio.sleep(1.1)

        downloader = TikTokDownloader(url)
        result_path = await downloader.download(filename)

        # Попробуем удалить оригинальное сообщение со ссылкой
        await safe_delete(message)

        # Отправляем скачанное видео
        await client.send_video(message.chat.id, video=result_path)

        # --- analytics ---
        if db and message.from_user:
            db.register_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
            db.log_download(message.from_user.id, 'tiktok', url)

    except ValueError as e:
        try: await msg.edit(f"❌ {e}")
        except Exception: pass
    except asyncio.TimeoutError:
        print("[TikTok] Error: read timeout")
        try: await msg.edit("❌ Таймаут: сервер долго отвечает. Попробуй позже.")
        except Exception: pass
    except aiohttp.ClientResponseError as e:
        print(f"[TikTok] HTTP error: {e}")
        try: await msg.edit(f"❌ HTTP ошибка: {e.status}")
        except Exception: pass
    except Exception as e:
        print(f"[TikTok] Unexpected error: {e}")
        try: await msg.edit("❌ Ошибка при скачивании видео.")
        except Exception: pass
    finally:
        await safe_delete(msg)
        cleanup_files(result_path, filename)
