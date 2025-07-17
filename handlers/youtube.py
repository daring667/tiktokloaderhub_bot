from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from services.youtube.youtube_downloader import YouTubeDownloader
from yt_dlp.utils import DownloadError as YTDownloadError
import re, os, time, logging

active_downloads = set()

def register(app: Client):
    @app.on_message(filters.regex(r'https?://(www\.)?youtu(be\.com|\.be)/') & (filters.group | filters.private))
    async def yt_handler(client: Client, message: Message):
        user_id = message.from_user.id

        if user_id in active_downloads:
            return await message.reply("⏳ Подожди, идёт другая загрузка.")

        active_downloads.add(user_id)
        filename = None

        try:
            print(f"💬 Сообщение от пользователя: {message.text}")

            url_match = re.search(r'https?://\S+', message.text)
            if not url_match:
                return await message.reply("❌ Не смог найти ссылку.")

            url = url_match.group(0).strip()
            print(f"🎯 Передаём ссылку в YouTubeDownloader: {url}")

            try:
                meta = YouTubeDownloader(url)
            except ValueError as e:
                await message.reply(f"❌ yt-dlp не смог распарсить ссылку: {e}")
                logging.error(f"YT download error: {e}")
                return

            # Если короткое видео или всего один формат — качаем сразу
            if len(meta.streams) == 1 or meta.length < 30:
                stream = meta.streams[0]
                filename = f"yt_{stream['itag']}_{int(time.time())}.mp4"
                await message.reply("⏬ Начинаем загрузку...")
                meta.download(stream['itag'], filename, message)
                await client.send_video(message.chat.id, filename, supports_streaming=True)
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

            await callback.message.edit_text("⏬ Начинаем загрузку...")

            meta = YouTubeDownloader(url)
            filename = f"yt_{itag}_{int(time.time())}.mp4"
            await meta.download(itag, filename, callback.message)

            await client.send_video(callback.message.chat.id, filename, supports_streaming=True)
            await callback.message.delete()

        except Exception as e:
            logging.error("Callback download error", exc_info=e)
            await callback.message.edit_text("❌ Ошибка при скачивании видео.")
        finally:
            if filename and os.path.exists(filename):
                os.remove(filename)
            active_downloads.discard(user_id)
