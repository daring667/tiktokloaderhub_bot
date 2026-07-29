from pyrogram import filters
from services.tiktok.tiktok_downloader import TikTokDownloader
from services.downloader import is_tiktok_url
from handlers.base import (
    BaseHandler,
    DownloadInProgress,
    RateLimited,
    rate_limit_message,
    download_slot,
    safe_delete,
    cleanup_files,
    user_key_for,
    report_error,
    extract_platform_urls,
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

            urls, total_found = extract_platform_urls(message.text, is_tiktok_url)
            if not urls:
                return await message.reply("❌ Не найдена ссылка.")

            try:
                async with download_slot(active_downloads, user_key_for(message)):
                    if total_found > len(urls):
                        await message.reply(f"⚠️ Нашёл {total_found} ссылок, обрабатываю первые {len(urls)}.")

                    any_success = False
                    for url in urls:
                        ok = await _download_and_send(client, message, url, db)
                        any_success = any_success or ok

                    if any_success:
                        await safe_delete(message)
            except DownloadInProgress:
                await message.reply("⏳ Подожди, идёт другая загрузка.")
            except RateLimited as e:
                await message.reply(rate_limit_message(e))


async def _download_and_send(client, message, url, db) -> bool:
    """Downloads and sends a single TikTok link. Returns True on success.
    Does not touch `message` itself — the caller may be processing several
    URLs against the same source message."""
    msg = await message.reply("⏳ Загружаю...")
    filename = os.path.join(DOWNLOADS_DIR, f"{uuid.uuid4()}.mp4")
    result_path = None
    success = False

    try:
        # Небольшая пауза (может помочь от спама)
        await asyncio.sleep(1.1)

        downloader = TikTokDownloader(url)
        result_path = await downloader.download(filename)

        # Отправляем скачанное видео
        await client.send_video(message.chat.id, video=result_path)
        success = True

        # --- analytics ---
        if db and message.from_user:
            db.register_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
            db.log_download(message.from_user.id, 'tiktok', url)

    except ValueError as e:
        try: await msg.edit(f"❌ {e}")
        except Exception: pass
        await report_error(client, "tiktok", url, message.from_user, e, db)
    except asyncio.TimeoutError as e:
        print("[TikTok] Error: read timeout")
        try: await msg.edit("❌ Таймаут: сервер долго отвечает. Попробуй позже.")
        except Exception: pass
        await report_error(client, "tiktok", url, message.from_user, e, db)
    except aiohttp.ClientResponseError as e:
        print(f"[TikTok] HTTP error: {e}")
        try: await msg.edit(f"❌ HTTP ошибка: {e.status}")
        except Exception: pass
        await report_error(client, "tiktok", url, message.from_user, e, db)
    except Exception as e:
        print(f"[TikTok] Unexpected error: {e}")
        try: await msg.edit("❌ Ошибка при скачивании видео.")
        except Exception: pass
        await report_error(client, "tiktok", url, message.from_user, e, db)
    finally:
        await safe_delete(msg)
        cleanup_files(result_path, filename)

    return success
