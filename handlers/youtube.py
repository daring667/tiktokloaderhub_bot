from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from services.youtube.youtube_downloader import YouTubeDownloader
import re
import os
import time
import logging
import string
import asyncio

active_downloads = set()


def extract_url(text: str) -> str | None:
    """Извлекает URL YouTube из текста сообщения"""
    youtube_regex = (
        r'(https?://)?(www\.)?'
        r'(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    match = re.search(youtube_regex, text)
    return match.group(0) if match else None


def should_download_immediately(url: str) -> bool:
    """Определяет, нужно ли скачивать видео сразу без выбора качества"""
    return any(x in url for x in ['shorts/', 'youtu.be/'])


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

            progress_msg = await message.reply("⏳ Обрабатываю видео...")

            try:
                downloader = YouTubeDownloader(url)
            except Exception as e:
                await progress_msg.edit_text(f"❌ Ошибка: {str(e)}")
                return

            # Для коротких видео сразу качаем
            if should_download_immediately(url):
                safe_title = sanitize_filename(getattr(downloader, 'title', 'video'))
                filename = f"downloads/{safe_title}_{int(time.time())}.mp4"

                # Создаем папку downloads если ее нет
                os.makedirs("downloads", exist_ok=True)

                success = await downloader.download('best', filename)
                if success:
                    await client.send_video(
                        message.chat.id,
                        filename,
                        caption=f"🎬 {getattr(downloader, 'title', 'YouTube видео')}",
                        supports_streaming=True
                    )
                else:
                    await progress_msg.edit_text("❌ Ошибка загрузки")

                await progress_msg.delete()
                return

            # Для обычных видео
            safe_title = sanitize_filename(getattr(downloader, 'title', 'video'))
            filename = f"downloads/{safe_title}_{int(time.time())}.mp4"
            os.makedirs("downloads", exist_ok=True)

            if len(getattr(downloader, 'streams', [])) == 1 or getattr(downloader, 'length', 0) < 30:
                stream = downloader.streams[0]
                await progress_msg.edit_text("⏬ Начинаем загрузку...")

                success = await downloader.download(stream['itag'], filename)
                if success:
                    await client.send_video(
                        message.chat.id,
                        filename,
                        caption=f"🎬 {getattr(downloader, 'title', 'YouTube видео')}",
                        supports_streaming=True
                    )
                else:
                    await progress_msg.edit_text("❌ Не удалось загрузить видео")

                await progress_msg.delete()
                return

            # Предлагаем выбор качества
            buttons = [
                InlineKeyboardButton(
                    f"{s['res']} - {round(s['filesize'] / 1024 / 1024, 1)}MB",
                    callback_data=f"yt|{url}|{s['itag']}"
                ) for s in getattr(downloader, 'streams', [])[:4]
            ]
            markup = InlineKeyboardMarkup.from_column(buttons)

            await progress_msg.edit_text(
                f"*🎬 {getattr(downloader, 'title', 'YouTube видео')}*\n⏱ {getattr(downloader, 'length', 0)} сек.\nВыбери качество:",
                reply_markup=markup,
                parse_mode="markdown"
            )

        except Exception as e:
            logging.exception("YouTube handler error")
            await message.reply(f"❌ Произошла ошибка: {str(e)}")
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
            downloader = YouTubeDownloader(url)
            safe_title = sanitize_filename(getattr(downloader, 'title', 'video'))
            filename = f"downloads/{safe_title}_{itag}_{int(time.time())}.mp4"
            os.makedirs("downloads", exist_ok=True)

            progress_msg = await callback.message.edit_text("⏬ Начинаем загрузку...")

            success = await downloader.download(itag, filename)
            if success:
                await client.send_video(
                    callback.message.chat.id,
                    filename,
                    caption=f"🎬 {getattr(downloader, 'title', 'YouTube видео')}",
                    supports_streaming=True
                )
                await callback.message.delete()
            else:
                await progress_msg.edit_text("❌ Ошибка при скачивании видео")
        except Exception as e:
            logging.error("Callback download error", exc_info=True)
            await callback.message.edit_text(f"❌ Ошибка: {str(e)}")
        finally:
            if filename and os.path.exists(filename):
                os.remove(filename)
            active_downloads.discard(user_id)