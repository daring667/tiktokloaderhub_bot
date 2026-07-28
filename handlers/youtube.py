from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.enums import ParseMode
from services.youtube.youtube_downloader import YouTubeDownloader
from services.downloader import extract_url
from services.utils.sanitize import sanitize_filename
from handlers.base import DownloadInProgress, download_slot, safe_delete, cleanup_files, user_key_for
from yt_dlp.utils import DownloadError as YTDownloadError
import re, os, time, logging, uuid

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

MAX_FILE_SIZE = 50 * 1024 * 1024

active_downloads = set()

async def process_and_send_video(
    client: Client,
    message: Message,
    meta: YouTubeDownloader,
    itag: str,
    url: str,
    db,
    user,
    is_audio: bool = False
):
    """
    Универсальная функция скачивания, переименования, отправки и сохранения в аналитику.
    """
    ext = '.mp3' if is_audio else '.mp4'
    filename = os.path.join(DOWNLOADS_DIR, f"{uuid.uuid4()}{ext}")
    status_msg = await message.reply("⏬ Начинаем загрузку...")
    result_path = None

    try:
        result_path = await meta.download(itag, filename, message, status_msg)
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Ошибка загрузки: {e}")
        except Exception:
            pass
        cleanup_files(filename)
        return

    # Переименуем файл в название видео (если доступно) перед отправкой
    try:
        title = getattr(meta, 'title', None)
        if title:
            safe = sanitize_filename(title)
            original_ext = os.path.splitext(result_path)[1]
            dirpath = os.path.dirname(result_path) or '.'
            new_name = f"{safe}{original_ext}"
            new_path = os.path.join(dirpath, new_name)
            if os.path.exists(new_path):
                new_path = os.path.join(dirpath, f"{safe}_{int(time.time())}{original_ext}")
            try:
                os.rename(result_path, new_path)
                result_path = new_path
            except Exception:
                pass
    except Exception:
        pass

    # Проверяем фактический размер файла — метаданные yt-dlp не всегда
    # содержат filesize, так что до этого момента лимит мог быть не применён
    try:
        actual_size = os.path.getsize(result_path) if result_path else 0
    except OSError:
        actual_size = 0

    if actual_size > MAX_FILE_SIZE:
        try:
            await status_msg.edit_text("❌ Файл больше 50 МБ — Telegram не позволяет ботам отправлять такие файлы.")
        except Exception:
            pass
        cleanup_files(result_path, filename)
        return

    # Отправляем соответствующим методом
    try:
        if is_audio:
            await client.send_audio(message.chat.id, result_path)
        else:
            await client.send_video(message.chat.id, result_path, supports_streaming=True)
    except Exception as e:
        logging.error(f"Error sending file: {e}")
        try:
            await status_msg.edit_text("❌ Ошибка при отправке файла.")
        except Exception:
            pass
        cleanup_files(result_path, filename)
        return

    # --- analytics ---
    if db and user:
        db.register_user(user.id, user.username, user.first_name)
        db.log_download(user.id, 'youtube', url)

    cleanup_files(result_path, filename)
    await safe_delete(status_msg)


def register(app: Client, db=None):
    @app.on_message(filters.regex(r'https?://(www\.)?youtu(be\.com|\.be)/') & (filters.group | filters.private))
    async def yt_handler(client: Client, message: Message):
        try:
            async with download_slot(active_downloads, user_key_for(message)):
                await _handle_youtube_link(client, message, db)
        except DownloadInProgress:
            await message.reply("⏳ Подожди, идёт другая загрузка.")

    @app.on_callback_query(filters.regex(r'^yt\|'))
    async def yt_callback(client, callback):
        try:
            async with download_slot(active_downloads, callback.from_user.id):
                await _handle_youtube_callback(client, callback, db)
        except DownloadInProgress:
            await callback.answer("⏳ Уже загружается...", show_alert=True)


async def _handle_youtube_link(client, message, db):
    try:
        print(f"💬 Сообщение от пользователя: {message.text}")

        url = extract_url(message.text)
        if not url:
            await message.reply("❌ Не смог найти ссылку.")
            return

        print(f"🎯 Передаём ссылку в YouTubeDownloader: {url}")

        try:
            meta = YouTubeDownloader(url)
        except ValueError as e:
            await message.reply(f"❌ yt-dlp не смог распарсить ссылку: {e}")
            logging.error(f"YT download error: {e}")
            return

        # Если видео короче или равно 2 минут — скачиваем сразу только в видео-формате
        if meta.length <= 120:
            video_stream = next((s for s in meta.streams if s.get('type') == 'video'), None)
            if not video_stream:
                await message.reply("❌ Нет доступного видео-формата для этого короткого видео.")
                return

            if not video_stream.get('filesize') or video_stream.get('filesize') <= 50 * 1024 * 1024:
                await process_and_send_video(client, message, meta, video_stream['itag'], url, db, message.from_user)
                return

        # Если всего один формат и это видео — качаем сразу
        if len(meta.streams) == 1 and meta.streams[0].get('type') == 'video':
            stream = meta.streams[0]
            if not stream.get('filesize') or stream.get('filesize') <= 50 * 1024 * 1024:
                await process_and_send_video(client, message, meta, stream['itag'], url, db, message.from_user)
                return

        # Иначе — предлагаем выбор качества
        buttons = []
        for s in meta.streams[:4]:
            if s.get('type') == 'audio' and meta.length <= 120:
                continue

            size = s.get('filesize')
            size_str = f"{round(size / 1024 / 1024, 1)}MB" if size else "unknown"
            label = f"{s.get('res')} - {size_str}"

            video_id = meta.url.split("v=")[-1] if "v=" in meta.url else None
            cb_data = f"yt|{s['itag']}|{video_id}" if video_id else None

            if not cb_data or len(cb_data.encode('utf-8')) > 64:
                token = uuid.uuid4().hex[:8]
                if db:
                    db.save_callback(token, url, s['itag'], s.get('type'))
                cb_data = f"yt|{token}"

            buttons.append(InlineKeyboardButton(label, callback_data=cb_data))

        markup = InlineKeyboardMarkup([[b] for b in buttons])
        await message.reply(
            f"*🎬 {meta.title}*\n⏱ {meta.length} сек.\nВыбери качество:",
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logging.exception("YouTube handler error")
        await message.reply("❌ Произошла ошибка при обработке видео.")


async def _handle_youtube_callback(client, callback, db):
    try:
        parts = callback.data.split("|")
        token = None

        if len(parts) == 3:
            _, itag, video_id = parts
            url = f"https://youtube.com/watch?v={video_id}"
        elif len(parts) == 2:
            _, token = parts
            mapping = db.get_callback(token) if db else None
            if not mapping:
                await callback.answer("❌ Срок действия кнопки истёк или она недействительна.", show_alert=True)
                return
            url = mapping['url']
            itag = mapping['itag']
        else:
            await callback.answer("❌ Неверный формат callback-данных.", show_alert=True)
            return

        meta = YouTubeDownloader(url)
        chosen_stream = next((s for s in meta.streams if str(s['itag']) == str(itag)), None)

        if chosen_stream and chosen_stream.get('filesize') and chosen_stream.get('filesize') > 50 * 1024 * 1024:
            await callback.answer("❌ Видео слишком большое (более 50 МБ). Попробуйте выбрать аудио или меньшее разрешение", show_alert=True)
            return

        is_audio = (chosen_stream and chosen_stream.get('type') == 'audio') or str(itag) == 'bestaudio'

        # Pass original message to process_and_send_video to keep reply context correct
        await process_and_send_video(client, callback.message, meta, itag, url, db, callback.from_user, is_audio)

        if token and db:
            db.delete_callback(token)

    except Exception as e:
        logging.error("Callback download error", exc_info=e)
        try:
            await callback.message.reply("❌ Ошибка при скачивании видео.")
        except Exception:
            pass
