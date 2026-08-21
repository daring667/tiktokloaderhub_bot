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
MERGED_VIDEO_FORMAT = (
    "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/"
    "best[ext=mp4][vcodec^=avc1]/best[ext=mp4]"
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


def is_playlist_url(url: str) -> bool:
    """True for a playlist link (`/playlist?list=...`) — but not for a
    single video that merely happens to carry a `list=` param because it
    was opened from within a playlist (`watch?v=X&list=Y`), which should
    still be treated as one video."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    has_video = bool(query.get("v", [None])[0])
    has_list = "list" in query or "/playlist" in parsed.path
    return has_list and not has_video


def get_playlist_info(playlist_url: str, limit: int = 25):
    """Fast (flat, no per-video probing) extraction of a playlist's videos.

    Returns (title, video_urls, total_count) — video_urls is capped at
    `limit` even if the playlist itself is bigger.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "geo_bypass": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
    except DownloadError as e:
        raise ValueError("yt-dlp не смог распарсить плейлист.") from e
    except Exception as e:
        raise ValueError("Произошла ошибка при обработке плейлиста.") from e

    if not info:
        raise ValueError("Не удалось получить информацию о плейлисте.")

    entries = info.get("entries") or []
    if not entries:
        raise ValueError("Плейлист пуст или недоступен.")

    title = info.get("title") or "Плейлист"
    total_count = len(entries)
    video_urls = [
        f"https://youtube.com/watch?v={e['id']}"
        for e in entries[:limit]
        if e.get("id")
    ]
    return title, video_urls, total_count


class YouTubeDownloader:

    def __init__(self, url: str):
        self.url = self.normalize_youtube_url(url)
        print(f"[log] Normalized URL: {self.url}")

        self.title = None
        self.length = None
        self.thumbnail = None
        self.streams = []

        base_opts = {
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

        attempts = [base_opts]
        if os.path.exists(COOKIES_PATH):
            fallback_opts = dict(base_opts)
            fallback_opts.pop("cookiefile", None)
            attempts.append(fallback_opts)

        android_opts = dict(base_opts)
        android_opts.pop("cookiefile", None)
        android_opts["extractor_args"] = {
            "youtube": {
                "player_client": ["android"],
                "player_skip": ["configs"],
            }
        }
        attempts.append(android_opts)

        info = None
        last_error = None

        try:
            for idx, opts in enumerate(attempts):
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(self.url, download=False)
                    break
                except DownloadError as e:
                    last_error = e
                    msg = str(e).lower()
                    if idx == len(attempts) - 1 or "page needs to be reloaded" not in msg:
                        if "requested format is not available" in msg and idx < len(attempts) - 1:
                            continue
                        raise
                    print("[DEBUG] yt-dlp reported a stale YouTube page; retrying without cookies.")

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

            # Shorts часто отдают только раздельные adaptive-потоки. В этом
            # случае yt-dlp может скачать лучший video+audio и объединить их
            # через ffmpeg, даже когда готового прогрессивного потока нет.
            video_only = [f for f in info.get("formats", [])
                          if f.get("vcodec") != "none" and f.get("acodec") == "none"]
            separate_audio = [f for f in info.get("formats", [])
                              if f.get("acodec") != "none" and f.get("vcodec") == "none"]
            if not self.streams and video_only and separate_audio:
                best_video = max(video_only, key=lambda x: x.get("height") or 0)
                best_audio = max(
                    separate_audio,
                    key=lambda x: x.get("filesize") or x.get("filesize_approx") or 0,
                )
                video_size = best_video.get("filesize") or best_video.get("filesize_approx") or 0
                audio_size = best_audio.get("filesize") or best_audio.get("filesize_approx") or 0
                self.streams.append({
                    "itag": MERGED_VIDEO_FORMAT,
                    "res": best_video.get("format_note") or best_video.get("resolution") or "best",
                    "filesize": video_size + audio_size or None,
                    "type": "video",
                })

            # Добавляем опцию аудио (MP3) на основе лучшего доступного аудио-формата
            audio_formats = separate_audio
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

        cookies_available = os.path.exists(COOKIES_PATH)
        if not cookies_available:
            print("[log] cookies.txt не найден — продолжаю без cookies")

        # Используем абсолютный путь для надёжности
        out_path = os.path.abspath(out_path)
        base_no_ext = os.path.splitext(out_path)[0]

        # Для аудио (mp3) используем bestaudio + ffmpeg-extract-audio postprocessor
        if itag == "bestaudio":
            opts = {
                "format": "bestaudio",
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
            if cookies_available:
                opts["cookiefile"] = COOKIES_PATH
            expected_path = base_no_ext + '.mp3'
        else:
            opts = {
                "format": itag,
                "outtmpl": base_no_ext + '.%(ext)s',
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [progress_callback]
            }
            if cookies_available:
                opts["cookiefile"] = COOKIES_PATH
            # возможные расширения видео
            expected_path = None

        try:
            # Try several fallbacks to reduce chance of HTTP 403 / "page needs to be reloaded"
            attempts = []
            attempts.append(opts)

            fb = dict(opts)
            if 'cookiefile' in fb:
                fb.pop('cookiefile')
            attempts.append(fb)

            fb2 = dict(fb)
            fb2.setdefault('http_headers', {})
            fb2['http_headers']['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0 Safari/537.36'
            attempts.append(fb2)

            android_fallback = dict(fb2)
            android_fallback['extractor_args'] = {
                'youtube': {
                    'player_client': ['android'],
                    'player_skip': ['configs'],
                }
            }
            attempts.append(android_fallback)

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
                    msg = str(e).lower()
                    if 'page needs to be reloaded' in msg or 'http error 403' in msg or 'forbidden' in msg:
                        print(f"[WARN] attempt {i} hit a YouTube anti-bot block; trying a safer client fallback.")
                        continue
                    print(f"[WARN] attempt {i} failed: {e}")

            if last_exc:
                raise last_exc

            # Cleanup of status_msg/message is the caller's responsibility
            # (handlers/youtube.py) — it may be processing several URLs
            # against the same source message in one batch.

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
