import os
from dotenv import load_dotenv
from pyrogram import Client
from handlers import youtube
from handlers.youtube import register
from services.youtube.youtube_downloader import fix_url
from services.tiktok.tiktok_downloader import TikTokDownloader
from handlers.youtube import register as register_youtube
from handlers.tiktok import TikTokHandler

load_dotenv()

app = Client(
    "tiktok_bot",
    api_id=int(os.getenv("API_KEY")),
    api_hash=os.getenv("API_HASH"),
    bot_token=os.getenv("BOT_TOKEN")
)

youtube.app = app  # pass client to handler

if __name__ == "__main__":
    register_youtube(app)
    TikTokHandler(app).register()
    print("🚀 Bot started!")

    app.run()
