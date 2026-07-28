from pyrogram import Client, filters
from services.instagram.instagram_downloader import InstagramDownloader
from services.downloader import extract_url
from services.utils.sanitize import sanitize_filename
import os, time, uuid, logging

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
active_downloads = set()

MAX_FILE_SIZE = 50 * 1024 * 1024


def register(app: Client, db=None):
    @app.on_message(filters.regex(r'https?://(www\.)?(instagram\.com/(reel|p|tv)/|instagr\.am/)') & (filters.group | filters.private))
    async def instagram_handler(client, message):
        user_key = message.from_user.id if message.from_user else f"chat:{message.chat.id}"

        if user_key in active_downloads:
            return await message.reply("⏳ Подожди, уже идет другая загрузка.")

        active_downloads.add(user_key)
        result_path = None
        status_msg = None
        filename = os.path.join(DOWNLOADS_DIR, f"{uuid.uuid4()}.mp4")

        try:
            url = extract_url(message.text or "")
            if not url:
                return await message.reply("❌ Не найдена ссылка Instagram.")

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
        except Exception as e:
            logging.exception("[Instagram] Упала загрузка")
            try:
                await message.reply("❌ Ошибка при скачивании Instagram-видео.")
            except Exception:
                pass
        finally:
            active_downloads.discard(user_key)
            try:
                await status_msg.delete()
            except Exception:
                pass
            if result_path and os.path.exists(result_path):
                try:
                    os.remove(result_path)
                except Exception:
                    pass
            if filename and os.path.exists(filename):
                try:
                    os.remove(filename)
                except Exception:
                    pass
