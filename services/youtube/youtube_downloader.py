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
        self.url = self.normalize_url(url)
        self.ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://www.youtube.com/',
            },
            'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
            'extractor_args': {'youtube': {'player_client': ['android']}},
            'retries': 5,
            'quiet': True
        }

    async def download(self, itag: str, output_path: str):
        loop = asyncio.get_event_loop()
        opts = {**self.ydl_opts, 'format': itag, 'outtmpl': output_path}

        try:
            def sync_download():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([self.url])

            await loop.run_in_executor(None, sync_download)
            return True
        except Exception as e:
            print(f"Download failed: {e}")
            return False

    @staticmethod
    def normalize_url(url: str) -> str:
        if "youtube.com/shorts/" in url:
            return url.replace("shorts/", "watch?v=").split("?")[0]
        if "youtu.be/" in url:
            return f"https://youtube.com/watch?v={url.split('youtu.be/')[1].split('?')[0]}"
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