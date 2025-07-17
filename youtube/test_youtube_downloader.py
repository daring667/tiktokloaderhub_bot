import yt_dlp

URL = "https://www.youtube.com/watch?v=rU181IgcKW0"  # сюда можно также вставить shorts
ydl_opts = {
    "quiet": True,
    "skip_download": True,  # сначала получение метаданных
}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(URL, download=False)
    formats = info["formats"]
    print(f"Найдено {len(formats)} форматов:")
    for f in formats[:5]:
        size = f.get("filesize") or f.get("filesize_approx") or 0
        print(f"- itag={f['format_id']}, {f.get('format_note') or f['ext']}, {size/1024/1024:.2f} MB")

    # Скачать лучшее видео+аудио
    best = info.get("best_format") or info["formats"][-1]
    ydl_opts2 = {"format": f"{best['format_id']}"}
    ydl2 = yt_dlp.YoutubeDL(ydl_opts2)
    ydl2.download([URL])
