import yt_dlp
from yt_dlp.utils import DownloadError
from urllib.parse import urlparse, parse_qs
from services.utils.progress_bar import progress
from services.utils.cookies_setup import setup_cookies
import time
import asyncio
import os

# Создаём cookies.txt, если нужно
setup_cookies()

COOKIES_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "cookies.txt")
)


def fix_url(url: str) -> str:
    """Нормализует URL YouTube и извлекает video_id, обрабатывая все форматы ссылок"""
    parsed = urlparse(url)

    if "youtu.be" in parsed.netloc:
        video_id = parsed.path[1:]
    elif "shorts/" in parsed.path:
        video_id = parsed.path.split("shorts/")[1].split("/")[0]
    else:
        query_params = parse_qs(parsed.query)
        video_id = query_params.get("v", [None])[0]

    if not video_id:
        raise ValueError("❌ Не удалось извлечь video_id из ссылки")

    return f"https://youtube.com/watch?v={video_id}"


class YouTubeDownloader:

    def __init__(self, url: str):
        self.url = self.normalize_youtube_url(url)
        print(f"[log] Normalized URL: {self.url}")

        self.title = None
        self.length = None
        self.thumbnail = None
        self.streams = []

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            # Use cookies + browser-like headers to reduce 403s from YouTube
            "cookiefile": COOKIES_PATH,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.youtube.com/"
            },
            "geo_bypass": True,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)

            if not info:
                raise ValueError("Не удалось получить информацию о видео.")

            self.title = info.get("title", "Без названия")
            self.length = info.get("duration", 0)
            self.thumbnail = info.get("thumbnail")

            # Собираем прогрессивные форматы (видео+аудио)
            for f in info.get("formats", []):
                # Некоторые форматы разделены (либо только видео, либо только аудио). Нам нужны прогрессивные форматы
                acodec = f.get("acodec")
                vcodec = f.get("vcodec")
                fmt_id = f.get("format_id")
                filesize = f.get("filesize") or f.get("filesize_approx")
                if acodec != 'none' and vcodec != 'none':
                    self.streams.append({
                        "itag": fmt_id,
                        "res": f.get("format_note") or f.get("resolution") or f.get("ext") or "video",
                        "filesize": filesize,
                        "type": "video"
                    })

            # Добавляем опцию аудио (MP3) на основе лучшего доступного аудио-формата
            audio_formats = [f for f in info.get("formats", []) if f.get("acodec") != 'none' and f.get("vcodec") == 'none']
            if audio_formats:
                best_audio = max(audio_formats, key=lambda x: x.get("filesize") or x.get("filesize_approx") or 0)
                audio_size = best_audio.get("filesize") or best_audio.get("filesize_approx")
                self.streams.append({
                    "itag": "bestaudio",
                    "res": "audio (mp3)",
                    "filesize": audio_size,
                    "type": "audio"
                })

            if not self.streams:
                raise ValueError("Нет подходящих форматов для загрузки.")

            # Сортируем по размеру чтобы предлагать сначала более крупные варианты
            self.streams.sort(key=lambda x: x["filesize"] or 0, reverse=True)

        except DownloadError as e:
            print(f"[DEBUG] yt-dlp DownloadError: {e}")
            raise ValueError("yt-dlp не смог распарсить ссылку.") from e
        except Exception as e:
            print(f"[DEBUG] Неизвестная ошибка: {e.__class__.__name__}: {e}")
            raise ValueError("Произошла непредвиденная ошибка при парсинге URL.") from e

    @staticmethod
    def normalize_youtube_url(url: str) -> str:
        return fix_url(url)

    def get_available_formats(self):
        return self.streams

    async def download(self, itag: str, out_path: str, message=None, status_msg=None):
        start_time = time.time()
        loop = asyncio.get_running_loop()
        import glob

        state = {'last_update': 0.0}

        def progress_callback(d):
            if d['status'] == 'downloading' and message:
                current = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                filename = d.get('filename', 'video')
                if total:
                    now = time.time()
                    if now - state['last_update'] >= 2.5 or current == total:
                        state['last_update'] = now
                        loop.call_soon_threadsafe(
                            lambda: asyncio.create_task(
                                progress(current, total, message, start_time, filename)
                            )
                        )

        if not os.path.exists(COOKIES_PATH):
            error_msg = f"❌ cookies.txt не найден по пути: {COOKIES_PATH}"
            print(error_msg)
            if status_msg:
                await status_msg.edit_text(error_msg)
            raise FileNotFoundError(error_msg)

        # Используем абсолютный путь для надёжности
        out_path = os.path.abspath(out_path)
        base_no_ext = os.path.splitext(out_path)[0]

        # Для аудио (mp3) используем bestaudio + ffmpeg-extract-audio postprocessor
        if itag == "bestaudio":
            opts = {
                "format": "bestaudio",
                "cookiefile": COOKIES_PATH,
                # Задаём шаблон без жёсткого расширения, чтобы postprocessor мог добавить .mp3
                "outtmpl": base_no_ext + '.%(ext)s',
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [progress_callback],
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192"
                }]
            }
            expected_path = base_no_ext + '.mp3'
        else:
            opts = {
                "format": itag,
                "cookiefile": COOKIES_PATH,
                "outtmpl": base_no_ext + '.%(ext)s',
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [progress_callback]
            }
            # возможные расширения видео
            expected_path = None

        try:
            # Try several fallbacks to reduce chance of HTTP 403
            attempts = []
            # Primary: use provided opts (may include cookiefile)
            attempts.append(opts)

            # Fallback: same opts but without cookiefile (some cookie files may be stale)
            fb = dict(opts)
            if 'cookiefile' in fb:
                fb.pop('cookiefile')
            attempts.append(fb)

            # Fallback: force different User-Agent
            fb2 = dict(fb)
            fb2.setdefault('http_headers', {})
            fb2['http_headers']['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0 Safari/537.36'
            attempts.append(fb2)

            last_exc = None
            for i, attempt_opts in enumerate(attempts, start=1):
                try:
                    print(f"[INFO] Download attempt {i}/{len(attempts)} using opts keys: {list(attempt_opts.keys())}")
                    await loop.run_in_executor(
                        None,
                        lambda opts=attempt_opts: yt_dlp.YoutubeDL(opts).download([self.url])
                    )
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    print(f"[WARN] attempt {i} failed: {e}")

            if last_exc:
                raise last_exc

            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            if message:
                try:
                    await message.delete()
                except Exception:
                    pass

            # Определяем реальный путь к скачанному файлу
            if expected_path and os.path.exists(expected_path):
                result_path = expected_path
            else:
                # Подбираем любой файл, начинающийся с base_no_ext
                matches = glob.glob(base_no_ext + '.*')
                # Отфильтруем временные/частичные файлы
                matches = [m for m in matches if not m.endswith('.part')]
                if matches:
                    # Берём первый подходящий
                    result_path = matches[0]
                else:
                    raise FileNotFoundError("Не удалось найти файл после завершения загрузки")

            return result_path

        except Exception as e:
            print(f"[ERROR] Download failed: {e}")
            # Let caller (handler) decide how to notify the user to avoid
            # attempting to edit the same status message twice.
            raise
