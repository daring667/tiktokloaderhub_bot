import os, asyncio, aiohttp

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tikwm.com/",
}

class TikTokDownloader:
    def __init__(self, url: str):
        self.url = url

    async def _get_tikwm_data(self):
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

    async def _download_file(self, video_url: str, filename: str):
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(video_url, timeout=aiohttp.ClientTimeout(total=120, connect=5)) as r:
                r.raise_for_status()
                with open(filename, "wb") as f:
                    async for chunk in r.content.iter_chunked(1024 * 1024):
                        if chunk:
                            f.write(chunk)

    async def download(self, filename: str) -> str:
        """
        Скачивает видео TikTok и сохраняет его в filename.
        Возвращает путь к сохраненному файлу (filename).
        Raises ValueError при проблемах или превышении лимита размера.
        Raises aiohttp / asyncio errors при сетевых сбоях.
        """
        data = await self._get_tikwm_data()
        
        # Check 50MB limit
        size = data.get("data", {}).get("size")
        if size and size > 50 * 1024 * 1024:
            raise ValueError("Видео слишком большое (более 50 МБ).")

        video_url = data.get("data", {}).get("play")
        if not video_url:
            raise ValueError("Не удалось получить видео из ответа API.")

        print(f"[TikTok] Download URL: {video_url}")
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        await self._download_file(video_url, filename)
        
        return filename