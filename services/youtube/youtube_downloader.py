import yt_dlp
from yt_dlp.utils import DownloadError
from urllib.parse import urlparse, parse_qs, urlencode
from services.utils.progress_bar import progress
import time
import asyncio


def fix_url(url: str) -> str:
    parsed = urlparse(url)
    if "shorts/" in parsed.path:
        video_id = parsed.path.split("shorts/")[1].split("/")[0]
    else:
        query_params = parse_qs(parsed.query)
        video_id = query_params.get("v", [None])[0]

    if not video_id:
        raise ValueError("❌ Невозможно вытащить video_id из ссылки!")

    query_params = parse_qs(parsed.query)
    query_string = urlencode({'v': video_id, **{k: v[0] for k, v in query_params.items() if k != 'v'}})
    return f"https://youtube.com/watch?{query_string}"


class YouTubeDownloader:

    def __init__(self, url: str):
        self.url = self.normalize_youtube_url(fix_url(url))
        print(f"[log] Normalized URL: {self.url}")
        self.title = None
        self.length = None
        self.thumbnail = None
        self.streams = []

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)

            if not info:
                raise ValueError("Не удалось получить информацию о видео.")

            self.title = info.get("title", "Без названия")
            self.length = info.get("duration", 0)
            self.thumbnail = info.get("thumbnail")

            for f in info.get("formats", []):
                if f.get("format_id") == "18":
                    self.streams.append({
                        "itag": f["format_id"],
                        "res": f.get("format_note") or f.get("resolution") or "unknown",
                        "filesize": f.get("filesize") or f.get("filesize_approx")
                    })

            if not self.streams:
                raise ValueError("Нет подходящих форматов для загрузки.")

            self.streams.sort(key=lambda x: x["filesize"] or 0, reverse=True)

        except DownloadError as e:
            print(f"[DEBUG] yt-dlp DownloadError: {e}")
            raise ValueError("yt-dlp не смог распарсить ссылку.") from e
        except Exception as e:
            print(f"[DEBUG] Неизвестная ошибка: {e.__class__.__name__}: {e}")
            raise ValueError("Произошла непредвиденная ошибка при парсинге URL.") from e

    @staticmethod
    def normalize_youtube_url(url: str) -> str:
        if "youtube.com/shorts/" in url:
            video_id = url.split("/shorts/")[1].split("?")[0]
            return f"https://youtube.com/watch?v={video_id}"
        if "watch?v=" in url:
            video_id = url.split("watch?v=")[1].split("&")[0]
            return f"https://youtube.com/watch?v={video_id}"
        return url

    def get_available_formats(self):
        return self.streams

    def download(self, itag: str, out_path: str, message=None):
        start_time = time.time()

        def hook(d):
            if d['status'] == 'downloading' and message:
                current = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                filename = d.get('filename', 'video')
                if total:
                    asyncio.create_task(progress(current, total, message, start_time, filename))

        opts = {
            'http_headers': {
                'User-Agent': 'Mozilla/5.0',
            },
                "format": itag,
                "outtmpl": out_path,
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [hook]

        }

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([self.url])
