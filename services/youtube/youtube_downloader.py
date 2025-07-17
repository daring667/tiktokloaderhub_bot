import yt_dlp
from yt_dlp.utils import DownloadError
from urllib.parse import urlparse, parse_qs, urlencode
import asyncio
import time

def _get_ydl_opts(self, itag: str, out_path: str):
    return {
        'format': f'{itag}+bestaudio/best',
        'outtmpl': out_path,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.youtube.com/',
        },
        'cookiefile': 'cookies.txt',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['hls', 'dash']
            }
        },
        'retries': 5,
        'ignoreerrors': True,
        'no_check_certificate': True,
        'quiet': True,
        'no_warnings': True
    }

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
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": "https://www.youtube.com/",
            }
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)

            if not info:
                raise ValueError("Не удалось получить информацию о видео.")

            self.title = info.get("title", "Без названия")
            self.length = info.get("duration", 0)
            self.thumbnail = info.get("thumbnail")

            # Получаем все доступные форматы
            for f in info.get("formats", []):
                if f.get("vcodec") != "none" and f.get("acodec") != "none":
                    self.streams.append({
                        "itag": f["format_id"],
                        "res": f.get("format_note") or f.get("resolution") or "unknown",
                        "filesize": f.get("filesize") or f.get("filesize_approx")
                    })

            if not self.streams:
                raise ValueError("Нет подходящих форматов для загрузки.")

            self.streams.sort(key=lambda x: x.get("filesize", 0), reverse=True)

        except DownloadError as e:
            raise ValueError(f"Ошибка загрузки: {e}") from e

    @staticmethod
    def normalize_youtube_url(url: str) -> str:
        if "youtube.com/shorts/" in url:
            video_id = url.split("/shorts/")[1].split("?")[0]
            return f"https://youtube.com/watch?v={video_id}"
        if "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0]
            return f"https://youtube.com/watch?v={video_id}"
        if "watch?v=" in url:
            video_id = url.split("watch?v=")[1].split("&")[0]
            return f"https://youtube.com/watch?v={video_id}"
        return url

    async def download(self, itag: str, out_path: str, message=None):
        ydl_opts = {
            'format': f'{itag}+bestaudio/best',
            'outtmpl': out_path,
            'http_headers': self._get_headers(),
            'cookiefile': "cookies.txt" if os.path.exists("cookies.txt") else None,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android'],
                    'skip': ['dash', 'hls']
                }
            },
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True,
        }

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([self.url]))
            return True
        except Exception as e:
            print(f"Download error: {e}")
            return False