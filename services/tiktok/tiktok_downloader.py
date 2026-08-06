import asyncio
import os

import aiohttp

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tikwm.com/",
}

# Five seconds to open a TCP connection is tight for a phone on mobile data
# reaching a CDN on another continent — the videos come from hosts like
# v45.tiktokcdn-us.com. A connect timeout that fires on a slow handshake
# looks to the user exactly like a broken bot.
CONNECT_TIMEOUT = 15

# One extra attempt, not a retry framework. The failure this addresses has
# happened once, and a transient blip is the likeliest cause; anything that
# fails twice in a row is a real problem the user should hear about rather
# than wait through.
NETWORK_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 1.5


async def _with_retry(make_attempt, what: str):
    """Runs `make_attempt`, retrying once on a transient network failure.

    Only connection-level errors are retried. An HTTP 404 or a malformed
    response will fail again for the same reason, so repeating it just makes
    the user wait twice as long for the same answer.
    """
    last_error = None
    for attempt in range(1, NETWORK_ATTEMPTS + 1):
        try:
            return await make_attempt()
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as exc:
            last_error = exc
            print(f"[TikTok] {what}: попытка {attempt}/{NETWORK_ATTEMPTS} "
                  f"не удалась ({type(exc).__name__})")
            if attempt < NETWORK_ATTEMPTS:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
    raise last_error

class TikTokDownloader:
    def __init__(self, url: str):
        self.url = url
        self._data = None

    async def _fetch_data(self):
        print(f"[TikTok] Requesting TikWM API for {self.url}")

        async def attempt():
            async with aiohttp.ClientSession(headers=HEADERS) as session:
                async with session.get(
                    "https://tikwm.com/api/",
                    params={"url": self.url},
                    timeout=aiohttp.ClientTimeout(total=30, connect=CONNECT_TIMEOUT)
                ) as res:
                    res.raise_for_status()
                    print(f"[TikTok] TikWM API status: {res.status}")
                    return await res.json()

        return await _with_retry(attempt, "запрос к API")

    async def probe(self) -> dict:
        """Fetches (and caches) tikwm metadata, so callers can check whether
        a post is a video or a photo slideshow before deciding which of
        download()/download_slideshow() to call."""
        if self._data is None:
            self._data = await self._fetch_data()
        return self._data

    async def _download_file(self, file_url: str, filename: str):
        async def attempt():
            async with aiohttp.ClientSession(headers=HEADERS) as session:
                async with session.get(
                    file_url,
                    timeout=aiohttp.ClientTimeout(total=120, connect=CONNECT_TIMEOUT),
                ) as r:
                    r.raise_for_status()
                    # "wb" truncates, so a retry after a partial download
                    # starts from an empty file rather than appending to it.
                    with open(filename, "wb") as f:
                        async for chunk in r.content.iter_chunked(1024 * 1024):
                            if chunk:
                                f.write(chunk)

        await _with_retry(attempt, "загрузка файла")

    async def download(self, filename: str) -> str:
        """
        Скачивает видео TikTok и сохраняет его в filename.
        Возвращает путь к сохраненному файлу (filename).
        Raises ValueError при проблемах, превышении лимита размера, или
        если ссылка ведёт на фото-слайдшоу (используйте download_slideshow).
        Raises aiohttp / asyncio errors при сетевых сбоях.
        """
        data = await self.probe()
        payload = data.get("data", {})

        if payload.get("images"):
            raise ValueError("Это фото-слайдшоу, а не видео.")

        # Check 50MB limit
        size = payload.get("size")
        if size and size > 50 * 1024 * 1024:
            raise ValueError("Видео слишком большое (более 50 МБ).")

        video_url = payload.get("play")
        if not video_url:
            raise ValueError("Не удалось получить видео из ответа API.")

        print(f"[TikTok] Download URL: {video_url}")
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        await self._download_file(video_url, filename)

        return filename

    async def download_slideshow(self, dirpath: str) -> list:
        """
        Скачивает все фото TikTok-слайдшоу в dirpath (музыку не трогаем).
        Returns список путей к скачанным изображениям, по порядку.
        Raises ValueError если это видео, а не слайдшоу.
        """
        data = await self.probe()
        payload = data.get("data", {})
        images = payload.get("images")
        if not images:
            raise ValueError("Это видео, а не фото-слайдшоу.")

        os.makedirs(dirpath, exist_ok=True)
        image_paths = []
        for i, image_url in enumerate(images):
            path = os.path.join(dirpath, f"image_{i}.jpg")
            await self._download_file(image_url, path)
            image_paths.append(path)

        return image_paths
