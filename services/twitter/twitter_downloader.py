import os
import glob
import asyncio
import yt_dlp
from yt_dlp.utils import DownloadError

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


class TwitterDownloader:
    def __init__(self, url: str):
        self.url = url
        self.title = None
        self._probe_video()

    def _probe_video(self):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "http_headers": DEFAULT_HEADERS,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)

            if not info:
                raise ValueError("Не удалось получить информацию о видео из Twitter/X.")

            self.title = info.get("title") or info.get("id") or "twitter_video"

        except DownloadError as e:
            raise ValueError("yt-dlp не смог распарсить ссылку Twitter/X.") from e
        except ValueError:
            raise
        except Exception as e:
            raise ValueError("Произошла ошибка при обработке ссылки Twitter/X.") from e

    async def download(self, output_path: str) -> str:
        out_path = os.path.abspath(output_path)
        base_no_ext = os.path.splitext(out_path)[0]
        os.makedirs(os.path.dirname(base_no_ext), exist_ok=True)

        opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": base_no_ext + '.%(ext)s',
            "quiet": True,
            "no_warnings": True,
            "http_headers": DEFAULT_HEADERS,
        }

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).download([self.url]))

        result_path = base_no_ext + '.mp4'
        if os.path.exists(result_path):
            return result_path

        candidates = glob.glob(base_no_ext + '.*')
        candidates = [p for p in candidates if not p.endswith('.part')]
        if candidates:
            return candidates[0]

        raise FileNotFoundError("Не удалось найти файл после скачивания видео из Twitter/X.")
