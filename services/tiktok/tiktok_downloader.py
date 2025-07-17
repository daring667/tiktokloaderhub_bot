import time, os, re, requests, asyncio
from pyrogram.types import Message

class TikTokDownloader:
    def __init__(self, message: Message):
        self.message = message
        self.url = self.extract_url()

    def extract_url(self):
        match = re.search(r'https?://\S+', self.message.text or "")
        return match.group(0) if match else None

    async def process(self):
        msg = await self.message.reply("⏳ Загружаю...")
        if not self.url:
            await msg.edit("❌ Не найдена ссылка.")
            return

        try:
            await asyncio.sleep(1.1)
            res = requests.get("https://tikwm.com/api/", params={"url": self.url}, timeout=10)
            data = res.json()
            video_url = data.get("data", {}).get("play")
            if not video_url:
                await msg.edit("❌ Не удалось получить видео.")
                return

            filename = f"{int(time.time())}.mp4"
            with requests.get(video_url, stream=True) as r:
                with open(filename, "wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk: f.write(chunk)

            await self.message.delete()
            await self.message._client.send_video(self.message.chat.id, video=filename)
            await msg.delete()
        except Exception as e:
            await msg.edit(f"❌ Ошибка: {e}")
        finally:
            if os.path.exists(filename):
                os.remove(filename)
