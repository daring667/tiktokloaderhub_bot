from pyrogram import filters
from services.tiktok.tiktok_downloader import TikTokDownloader
from handlers.base import BaseHandler

class TikTokHandler(BaseHandler):
    def register(self):
        @self.app.on_message(filters.regex(r'https?://.*tiktok\.com/'))
        async def handle_tiktok(client, message):
            downloader = TikTokDownloader(message)
            await downloader.process()
