from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.enums import ParseMode
from services.youtube.youtube_downloader import YouTubeDownloader, is_playlist_url, get_playlist_info
from services.downloader import is_youtube_url
from services.utils.sanitize import sanitize_filename
from handlers.base import (
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
import html, os, time, logging, uuid

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_PLAYLIST_ITEMS = 25

# Outcomes of handling a single URL. A playlist must tell them apart: after
# SENT it can offer the next video right away, but after PICKER it has to
# wait for the user to choose a quality first.
RESULT_SENT = "sent"
RESULT_PICKER = "picker"
RESULT_FAILED = "failed"


def format_duration(seconds) -> str:
    seconds = int(seconds or 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

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
    Returns True on success, False otherwise. Does not touch `message` itself —
    the caller may be processing several URLs against the same source message.
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
        await report_error(client, "youtube", url, user, e, db)
        return False

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
        return False

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
        await report_error(client, "youtube", url, user, e, db)
        return False

    # --- analytics ---
    if db and user:
        db.register_user(user.id, user.username, user.first_name)
        db.log_download(user.id, 'youtube', url)

    cleanup_files(result_path, filename)
    await safe_delete(status_msg)
    return True


def register(app: Client, db=None):
    @app.on_message(filters.regex(r'https?://(www\.)?youtu(be\.com|\.be)/') & (filters.group | filters.private))
    async def yt_handler(client: Client, message: Message):
        urls, total_found = extract_platform_urls(message.text, is_youtube_url)
        if not urls:
            await message.reply("❌ Не смог найти ссылку.")
            return

        try:
            async with download_slot(active_downloads, user_key_for(message)):
                if total_found > len(urls):
                    await message.reply(f"⚠️ Нашёл {total_found} ссылок, обрабатываю первые {len(urls)}.")

                any_success = False
                for url in urls:
                    result = await _handle_one_youtube_url(client, message, db, url)
                    # A playlist keeps its source message: the step-through
                    # prompts reply to it, and the user may want the link back
                    # after picking through the videos.
                    if result != RESULT_FAILED and not is_playlist_url(url):
                        any_success = True

                if any_success:
                    await safe_delete(message)
        except DownloadInProgress:
            await message.reply("⏳ Подожди, идёт другая загрузка.")
        except RateLimited as e:
            await message.reply(rate_limit_message(e))

    @app.on_callback_query(filters.regex(r'^yt\|'))
    async def yt_callback(client, callback):
        data = callback.data

        if data == "yt|cancel":
            await safe_delete(callback.message)
            await callback.answer("Отменено")
            return

        if data.startswith("yt|plstop|"):
            token = data.split("|", 2)[2]
            await _handle_playlist_stop(callback, db, token)
            return

        if data.startswith("yt|plnext|"):
            token = data.split("|", 2)[2]
            try:
                # No cooldown here: this button is meant to be pressed right
                # after the previous video finished downloading.
                async with download_slot(active_downloads, callback.from_user.id, enforce_cooldown=False):
                    await _handle_playlist_next(client, callback, db, token)
            except DownloadInProgress:
                await callback.answer("⏳ Уже загружается...", show_alert=True)
            except RateLimited as e:
                await callback.answer(rate_limit_message(e), show_alert=True)
            return

        try:
            async with download_slot(active_downloads, callback.from_user.id):
                await _handle_youtube_callback(client, callback, db)
        except DownloadInProgress:
            await callback.answer("⏳ Уже загружается...", show_alert=True)
        except RateLimited as e:
            await callback.answer(rate_limit_message(e), show_alert=True)


async def _handle_one_youtube_url(client, message, db, url, playlist_token=None) -> str:
    """Processes a single YouTube URL found in `message`.

    Returns RESULT_SENT / RESULT_PICKER / RESULT_FAILED — callers use this
    both to decide whether the source message is safe to delete, and (for
    playlists) whether the next video can be offered immediately.
    """
    if is_playlist_url(url):
        return await _start_playlist(client, message, db, url)

    try:
        print(f"🎯 Передаём ссылку в YouTubeDownloader: {url}")

        try:
            meta = YouTubeDownloader(url)
        except ValueError as e:
            await message.reply(f"❌ yt-dlp не смог распарсить ссылку: {e}")
            logging.error(f"YT download error: {e}")
            await report_error(client, "youtube", url, message.from_user, e, db)
            return RESULT_FAILED

        # Если видео короче или равно 2 минут — скачиваем сразу только в видео-формате
        if meta.length <= 120:
            video_stream = next((s for s in meta.streams if s.get('type') == 'video'), None)
            if not video_stream:
                await message.reply("❌ Нет доступного видео-формата для этого короткого видео.")
                return RESULT_FAILED

            if not video_stream.get('filesize') or video_stream.get('filesize') <= 50 * 1024 * 1024:
                ok = await process_and_send_video(client, message, meta, video_stream['itag'], url, db, message.from_user)
                return RESULT_SENT if ok else RESULT_FAILED

        # Если всего один формат и это видео — качаем сразу
        if len(meta.streams) == 1 and meta.streams[0].get('type') == 'video':
            stream = meta.streams[0]
            if not stream.get('filesize') or stream.get('filesize') <= 50 * 1024 * 1024:
                ok = await process_and_send_video(client, message, meta, stream['itag'], url, db, message.from_user)
                return RESULT_SENT if ok else RESULT_FAILED

        # Иначе — предлагаем выбор качества.
        # Видео всегда идёт раньше аудио, независимо от размера файла —
        # иначе маленькое аудио может внезапно оказаться выше 360p в списке.
        candidates = [
            s for s in meta.streams[:4]
            if not (s.get('type') == 'audio' and meta.length <= 120)
        ]
        candidates.sort(key=lambda s: s.get('type') == 'audio')

        buttons = []
        for s in candidates:
            size = s.get('filesize')
            size_str = f"{round(size / 1024 / 1024, 1)} МБ" if size else "размер неизвестен"
            if s.get('type') == 'audio':
                label = f"🎵 Аудио (mp3) — {size_str}"
            else:
                label = f"🎬 {s.get('res')} — {size_str}"

            video_id = meta.url.split("v=")[-1] if "v=" in meta.url else None
            cb_data = f"yt|{s['itag']}|{video_id}" if video_id else None

            # Inside a playlist the callback must carry the session token, so
            # go through the database rather than packing it into the inline
            # data (which is capped at 64 bytes).
            if playlist_token or not cb_data or len(cb_data.encode('utf-8')) > 64:
                token = uuid.uuid4().hex[:8]
                if db:
                    db.save_callback(token, url, s['itag'], s.get('type'), playlist_token)
                cb_data = f"yt|{token}"

            buttons.append(InlineKeyboardButton(label, callback_data=cb_data))

        markup_rows = [[b] for b in buttons]
        markup_rows.append([InlineKeyboardButton("❌ Отмена", callback_data="yt|cancel")])
        markup = InlineKeyboardMarkup(markup_rows)
        title_safe = html.escape(meta.title or "Без названия")
        await message.reply(
            f"🎬 <b>{title_safe}</b>\n⏱ {format_duration(meta.length)}\nВыбери качество:",
            reply_markup=markup,
            parse_mode=ParseMode.HTML
        )
        return RESULT_PICKER

    except Exception as e:
        logging.exception("YouTube handler error")
        await message.reply("❌ Произошла ошибка при обработке видео.")
        await report_error(client, "youtube", url, message.from_user, e, db)
        return RESULT_FAILED


async def _start_playlist(client, message, db, playlist_url) -> str:
    """Downloads the first video of a playlist, then offers to step
    through the rest one at a time rather than downloading it all at once."""
    try:
        title, video_urls, total_count = get_playlist_info(playlist_url, limit=MAX_PLAYLIST_ITEMS)
    except ValueError as e:
        await message.reply(f"❌ {e}")
        await report_error(client, "youtube", playlist_url, message.from_user, e, db)
        return RESULT_FAILED

    if not video_urls:
        await message.reply("❌ Не нашёл видео в этом плейлисте.")
        return RESULT_FAILED

    if not db:
        # Without a database there's nowhere to keep step-through state —
        # fall back to just the first video.
        return await _handle_one_youtube_url(client, message, db, video_urls[0])

    token = uuid.uuid4().hex[:12]
    db.save_playlist_state(token, video_urls, total_count)

    title_safe = html.escape(title)
    await message.reply(f"📃 Плейлист «{title_safe}» — {total_count} видео.\nСкачиваю первое...")

    result = await _handle_one_youtube_url(client, message, db, video_urls[0], playlist_token=token)
    # If a quality picker is on screen, the next-video prompt would compete
    # with it — offer the next one only once this video is actually done.
    if result != RESULT_PICKER:
        await _offer_next_playlist_video(message, db, token)
    return result


async def _offer_next_playlist_video(message, db, token):
    """Sends the "download the next one?" prompt, or cleans up silently
    if the step-through session has reached the end of the list."""
    state = db.get_playlist_state(token)
    if not state:
        return

    next_index = state["index_pos"] + 1
    if next_index >= len(state["video_urls"]):
        db.delete_playlist_state(token)
        return

    remaining = len(state["video_urls"]) - next_index
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("▶️ Следующее видео", callback_data=f"yt|plnext|{token}"),
        InlineKeyboardButton("❌ Хватит", callback_data=f"yt|plstop|{token}"),
    ]])
    await message.reply(
        f"Осталось ещё {remaining} видео из плейлиста. Скачать следующее?",
        reply_markup=markup,
    )


async def _handle_playlist_stop(callback, db, token):
    db.delete_playlist_state(token)
    await safe_delete(callback.message)
    await callback.answer("Ок, на этом всё.")


async def _handle_playlist_next(client, callback, db, token):
    state = db.advance_playlist_state(token)
    if not state or state["index_pos"] >= len(state["video_urls"]):
        db.delete_playlist_state(token)
        try:
            await callback.message.edit_text("Плейлист закончился.")
        except Exception:
            pass
        await callback.answer()
        return

    await callback.answer()
    next_url = state["video_urls"][state["index_pos"]]

    # Keep the prompt around while the next video is being handled: it is the
    # message everything below replies to. Removing it first left those
    # replies pointing at a deleted message.
    prompt = callback.message
    result = await _handle_one_youtube_url(client, prompt, db, next_url, playlist_token=token)
    if result != RESULT_PICKER:
        await _offer_next_playlist_video(prompt, db, token)
    await safe_delete(prompt)


async def _handle_youtube_callback(client, callback, db):
    try:
        parts = callback.data.split("|")
        token = None
        playlist_token = None

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
            playlist_token = mapping.get('playlist_token')
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
        ok = await process_and_send_video(client, callback.message, meta, itag, url, db, callback.from_user, is_audio)

        # This picker belonged to a playlist — now that the user has finally
        # chosen a quality, it's time to offer the next video.
        if ok and playlist_token and db:
            await _offer_next_playlist_video(callback.message, db, playlist_token)

        if ok:
            await safe_delete(callback.message)

        if token and db:
            db.delete_callback(token)

    except Exception as e:
        logging.error("Callback download error", exc_info=e)
        try:
            await callback.message.reply("❌ Ошибка при скачивании видео.")
        except Exception:
            pass
        await report_error(client, "youtube", callback.data, callback.from_user, e, db)
