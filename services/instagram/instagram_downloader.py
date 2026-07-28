import os
import glob
import time
import asyncio
import yt_dlp
from yt_dlp.utils import DownloadError
import subprocess
import shutil
from services.utils.cookies_setup import setup_cookies

setup_cookies()

COOKIES_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "cookies.txt")
)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/",
}


class InstagramDownloader:
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
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "prefer_ffmpeg": True,
            # Ensure final output is transcoded to H.264/AAC in mp4 container
            "recode_video": "mp4",
        }

        if os.path.exists(COOKIES_PATH):
            opts["cookiefile"] = COOKIES_PATH

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)

            if not info:
                raise ValueError("Не удалось получить информацию о видео Instagram.")

            self.title = info.get("title") or info.get("id") or "instagram_video"

        except DownloadError as e:
            raise ValueError("yt-dlp не смог распарсить Instagram-ссылку.") from e
        except ValueError:
            raise
        except Exception as e:
            raise ValueError("Произошла ошибка при обработке Instagram-ссылки.") from e

    async def download(self, output_path: str) -> str:
        out_path = os.path.abspath(output_path)
        base_no_ext = os.path.splitext(out_path)[0]
        os.makedirs(os.path.dirname(base_no_ext), exist_ok=True)

        opts = {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "prefer_ffmpeg": True,
            # Force ffmpeg to transcode to mp4 (H.264 + AAC) to avoid incompatible codecs
            "recode_video": "mp4",
            "outtmpl": base_no_ext + '.%(ext)s',
            "quiet": True,
            "no_warnings": True,
            "http_headers": DEFAULT_HEADERS,
        }

        if os.path.exists(COOKIES_PATH):
            opts["cookiefile"] = COOKIES_PATH

        attempts = [opts]
        fallback = dict(opts)
        fallback.pop("cookiefile", None)
        attempts.append(fallback)
        fallback_alt = dict(fallback)
        fallback_alt.setdefault("http_headers", {})
        fallback_alt["http_headers"]["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0 Safari/537.36"
        attempts.append(fallback_alt)

        loop = asyncio.get_running_loop()
        last_exc = None

        for i, attempt_opts in enumerate(attempts, start=1):
            try:
                await loop.run_in_executor(
                    None,
                    lambda opts=attempt_opts: yt_dlp.YoutubeDL(opts).download([self.url])
                )
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                print(f"[Instagram] download attempt {i} failed: {exc}")

        if last_exc:
            raise last_exc

        result_path = base_no_ext + '.mp4'
        if os.path.exists(result_path):
            # If ffmpeg exists, transcode to H.264/AAC to ensure broad compatibility
            if shutil.which("ffmpeg"):
                recoded = base_no_ext + '_h264.mp4'
                try:
                    def _ffmpeg_transcode(inp, outp):
                        cmd = [
                            'ffmpeg', '-y', '-i', inp,
                            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                            '-pix_fmt', 'yuv420p',
                            '-movflags', '+faststart',
                            '-c:a', 'aac', '-b:a', '128k', outp
                        ]
                        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                    await loop.run_in_executor(None, _ffmpeg_transcode, result_path, recoded)
                    try:
                        os.remove(result_path)
                    except Exception:
                        pass
                    if os.path.exists(recoded):
                        return recoded
                except Exception as e:
                    print(f"[Instagram] ffmpeg transcode failed: {e}")
                    # Fall through and return original if transcode fails
            return result_path

        candidates = glob.glob(base_no_ext + '.*')
        candidates = [path for path in candidates if not path.endswith('.part')]
        if candidates:
            return candidates[0]

        raise FileNotFoundError("Не удалось найти файл после скачивания Instagram-видео.")
