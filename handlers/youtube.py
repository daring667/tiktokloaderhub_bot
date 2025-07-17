from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from services.youtube.youtube_downloader import YouTubeDownloader
from yt_dlp.utils import DownloadError as YTDownloadError
import re, os, time, logging
import string
active_downloads = set()

def sanitize_filename(name: str) -> str:
    allowed_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    return ''.join(c for c in name if c in allowed_chars)

def register(app: Client):
    @app.on_message(filters.regex(r'https?://(www\.)?youtu(be\.com|\.be)/') & (filters.group | filters.private))
    async def yt_handler(client: Client, message: Message):
        user_id = message.from_user.id
        if user_id in active_downloads:
            return await message.reply("⏳ Подожди, идёт другая загрузка.")

        active_downloads.add(user_id)
        filename = None

        try:
            url = extract_url(message.text)
            if not url:
                return await message.reply("❌ Неверная ссылка")

            progress_msg = await message.reply("⏳ Начинаем загрузку...")
            downloader = YouTubeDownloader(url)

            # Для коротких видео сразу качаем
            if should_download_immediately(url):
                filename = f"downloads/video_{int(time.time())}.mp4"
                success = await downloader.download('best', filename)

                if success:
                    await client.send_video(
                        message.chat.id,
                        filename,
                        supports_streaming=True
                    )
                else:
                    await progress_msg.edit_text("❌ Ошибка загрузки")

                return

            safe_title = sanitize_filename(meta.title)
            filename = f"downloads/{safe_title}_{int(time.time())}.mp4"

            await asyncio.sleep(1)  # Задержка между запросами

            if len(meta.streams) == 1 or meta.length < 30:
                stream = meta.streams[0]
                await progress_msg.edit_text("⏬ Начинаем загрузку...")

                success = await meta.download(stream['itag'], filename, progress_msg)
                if success:
                    await client.send_video(
                        message.chat.id,
                        filename,
                        caption=f"🎬 {meta.title}",
                        supports_streaming=True
                    )
                else:
                    await progress_msg.edit_text("❌ Не удалось загрузить видео")

                await progress_msg.delete()
                return

            # Иначе — предлагаем выбор качества
            buttons = [
                InlineKeyboardButton(
                    f"{s['res']} - {round(s['filesize'] / 1024 / 1024, 1)}MB",
                    callback_data=f"yt|{url}|{s['itag']}"
                ) for s in meta.streams[:4]
            ]
            markup = InlineKeyboardMarkup.from_column(buttons)

            await message.reply(
                f"*🎬 {meta.title}*\n⏱ {meta.length} сек.\nВыбери качество:",
                reply_markup=markup,
                parse_mode="markdown"
            )

        except Exception as e:
            logging.exception("YouTube handler error")
            await message.reply("❌ Произошла ошибка при обработке видео.")

        finally:
            if filename and os.path.exists(filename):
                os.remove(filename)
            active_downloads.discard(user_id)

    @app.on_callback_query(filters.regex(r'^yt\|'))
    async def yt_callback(client, callback):
        user_id = callback.from_user.id

        if user_id in active_downloads:
            return await callback.answer("⏳ Уже загружается...", show_alert=True)

        active_downloads.add(user_id)
        filename = None

        try:
            _, url, itag = callback.data.split("|")
            print(f"⬇️ Callback-ссылка: {url}")

            meta = YouTubeDownloader(url)
            safe_title = sanitize_filename(meta.title)
            filename = f"/app/downloads/yt_{itag}_{int(time.time())}.mp4"

            progress_msg = callback.message
            await progress_msg.edit_text("⏬ Начинаем загрузку...")

            await meta.download(itag, filename, callback.message)
            await client.send_video(callback.message.chat.id, filename, supports_streaming=True)
            await progress_msg.delete()
        except Exception as e:
            logging.error("Callback download error", exc_info=True)
            await callback.message.edit_text("❌ Ошибка при скачивании видео.")
        finally:
            if filename and os.path.exists(filename):
                os.remove(filename)
            active_downloads.discard(user_id)
