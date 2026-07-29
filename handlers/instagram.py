from pyrogram import Client, filters
from services.instagram.instagram_downloader import InstagramDownloader
from services.downloader import is_instagram_url
from services.utils.sanitize import sanitize_filename
from handlers.base import (
    DownloadInProgress,
    download_slot,
    safe_delete,
    cleanup_files,
    user_key_for,
    report_error,
    extract_platform_urls,
)
import os, time, uuid, logging

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
active_downloads = set()

MAX_FILE_SIZE = 50 * 1024 * 1024


def register(app: Client, db=None):
    @app.on_message(filters.regex(r'https?://(www\.)?(instagram\.com/(reel|p|tv)/|instagr\.am/)') & (filters.group | filters.private))
    async def instagram_handler(client, message):
        urls, total_found = extract_platform_urls(message.text, is_instagram_url)
        if not urls:
            return await message.reply("❌ Не найдена ссылка Instagram.")

        try:
            async with download_slot(active_downloads, user_key_for(message)):
                if total_found > len(urls):
                    await message.reply(f"⚠️ Нашёл {total_found} ссылок, обрабатываю первые {len(urls)}.")
                for url in urls:
                    await _download_and_send(client, message, db, url)
        except DownloadInProgress:
            await message.reply("⏳ Подожди, уже идет другая загрузка.")


async def _download_and_send(client, message, db, url):
    result_path = None
    status_msg = None
    filename = os.path.join(DOWNLOADS_DIR, f"{uuid.uuid4()}.mp4")

    try:
        status_msg = await message.reply("⏳ Загружаю Instagram Reels...")
        downloader = InstagramDownloader(url)
        result_path = await downloader.download(filename)

        safe_name = sanitize_filename(downloader.title)
        ext = os.path.splitext(result_path)[1] or ".mp4"
        new_path = os.path.join(DOWNLOADS_DIR, f"{safe_name}{ext}")
        if os.path.exists(new_path):
            new_path = os.path.join(DOWNLOADS_DIR, f"{safe_name}_{int(time.time())}{ext}")
        try:
            os.rename(result_path, new_path)
            result_path = new_path
        except Exception:
            pass

        # yt-dlp не всегда знает точный размер Instagram-видео заранее,
        # поэтому лимит в 50 МБ проверяем по факту скачанного файла
        try:
            actual_size = os.path.getsize(result_path) if result_path else 0
        except OSError:
            actual_size = 0

        if actual_size > MAX_FILE_SIZE:
            try:
                await status_msg.edit_text("❌ Видео больше 50 МБ — Telegram не позволяет ботам отправлять такие файлы.")
            except Exception:
                pass
            return

        try:
            # Send without supports_streaming to avoid player trying to stream
            await client.send_video(message.chat.id, result_path)
        except Exception as e:
            logging.error(f"[Instagram] send_video failed: {e}")
            await status_msg.edit_text("❌ Ошибка при отправке Instagram-видео.")
            await report_error(client, "instagram", url, message.from_user, e, db)
            return

        if db and message.from_user:
            db.register_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
            db.log_download(message.from_user.id, 'instagram', url)

    except ValueError as e:
        logging.warning(f"[Instagram] ValueError: {e}")
        try:
            await message.reply(f"❌ {e}")
        except Exception:
            pass
        await report_error(client, "instagram", url, message.from_user, e, db)
    except Exception as e:
        logging.exception("[Instagram] Упала загрузка")
        try:
            await message.reply("❌ Ошибка при скачивании Instagram-видео.")
        except Exception:
            pass
        await report_error(client, "instagram", url, message.from_user, e, db)
    finally:
        await safe_delete(status_msg)
        cleanup_files(result_path, filename)
