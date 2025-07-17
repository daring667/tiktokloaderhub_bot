from yt_dlp import YoutubeDL

url = input("Вставь ссылку: ")

opts = {
    'quiet': False,
    'skip_download': True,
    'noplaylist': True,
    'format': 'bestvideo+bestaudio/best',
}

try:
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        print("[OK] Всё сработало!")
        print(f"Title: {info.get('title')}")
        print(f"Duration: {info.get('duration')}")
        print(f"Thumbnail: {info.get('thumbnail')}")
except Exception as e:
    print(f"[ERROR] {e.__class__.__name__}: {e}")
