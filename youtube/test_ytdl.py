from services.youtube.youtube_downloader import YouTubeDownloader
from pathlib import Path

url = input("Вставь ссылку на YouTube/Shorts: ")

try:
    downloader = YouTubeDownloader(url)

    print(f"\n🎬 Название: {downloader.title}")
    print(f"⏱ Длительность: {downloader.length} сек.")
    print(f"🖼 Превью: {downloader.thumbnail}")
    print(f"\n📥 Доступные форматы:")

    for i, fmt in enumerate(downloader.get_available_formats(), start=1):
        size_mb = round(fmt['filesize'] / (1024 ** 2), 2)
        print(f"{i}. {fmt['res']} — {size_mb} MB — itag: {fmt['itag']}")

    choice = int(input("\nВыбери формат (номер): ")) - 1
    itag = downloader.get_available_formats()[choice]['itag']
    out_file = str(Path(f"./video.mp4").resolve())

    print(f"\n📦 Скачиваем в {out_file} ...")
    downloader.download(itag, out_file)
    print("✅ Готово!")

except Exception as e:
    print(f"❌ Ошибка: {e}")
