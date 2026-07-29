from pyrogram import filters
from pyrogram.types import InputMediaPhoto
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
import os, shutil, uuid, aiohttp, asyncio

MEDIA_GROUP_LIMIT = 10  # Telegram's max items per send_media_group call

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


async def _send_slideshow(client, chat_id, image_paths):
    """TikTok photo posts can have more images than Telegram allows in one
    media group (10), so send them in chunks."""
    for i in range(0, len(image_paths), MEDIA_GROUP_LIMIT):
        chunk = image_paths[i:i + MEDIA_GROUP_LIMIT]
        await client.send_media_group(chat_id, [InputMediaPhoto(p) for p in chunk])


async def _download_and_send(client, message, url, db) -> bool:
    """Downloads and sends a single TikTok link — a video or a photo
    slideshow, whichever it turns out to be. Returns True on success.
    Does not touch `message` itself — the caller may be processing several
    URLs against the same source message."""
    msg = await message.reply("⏳ Загружаю...")
    filename = os.path.join(DOWNLOADS_DIR, f"{uuid.uuid4()}.mp4")
    result_path = None
    slideshow_dir = None
    success = False

    try:
        # Небольшая пауза (может помочь от спама)
        await asyncio.sleep(1.1)

        downloader = TikTokDownloader(url)
        data = await downloader.probe()
        is_slideshow = bool(data.get("data", {}).get("images"))

        if is_slideshow:
            slideshow_dir = os.path.join(DOWNLOADS_DIR, f"slideshow_{uuid.uuid4()}")
            image_paths = await downloader.download_slideshow(slideshow_dir)
            await _send_slideshow(client, message.chat.id, image_paths)
        else:
            result_path = await downloader.download(filename)
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
        if slideshow_dir:
            shutil.rmtree(slideshow_dir, ignore_errors=True)

    return success
