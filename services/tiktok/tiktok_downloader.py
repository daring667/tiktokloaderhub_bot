import os, asyncio, aiohttp

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tikwm.com/",
}

class TikTokDownloader:
    def __init__(self, url: str):
        self.url = url
        self._data = None

    async def _fetch_data(self):
        print(f"[TikTok] Requesting TikWM API for {self.url}")
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(
                "https://tikwm.com/api/",
                params={"url": self.url},
                timeout=aiohttp.ClientTimeout(total=30, connect=5)
            ) as res:
                res.raise_for_status()
                print(f"[TikTok] TikWM API status: {res.status}")
                return await res.json()

    async def probe(self) -> dict:
        """Fetches (and caches) tikwm metadata, so callers can check whether
        a post is a video or a photo slideshow before deciding which of
        download()/download_slideshow() to call."""
        if self._data is None:
            self._data = await self._fetch_data()
        return self._data

    async def _download_file(self, file_url: str, filename: str):
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(file_url, timeout=aiohttp.ClientTimeout(total=120, connect=5)) as r:
                r.raise_for_status()
                with open(filename, "wb") as f:
                    async for chunk in r.content.iter_chunked(1024 * 1024):
                        if chunk:
                            f.write(chunk)

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
