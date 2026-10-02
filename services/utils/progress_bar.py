from pyrogram.types import Message
import math
import time

async def progress(current, total, message: Message, start, filename, completed_bytes=0):
    """Render a download progress update.

    ``yt-dlp`` invokes a hook independently for the video and audio tracks
    of an adaptive YouTube format. ``completed_bytes`` carries the tracks
    that already finished, so the user sees the total transfer rather than
    the last 8 MB audio track after a much larger video download.
    """
    now = time.time()
    diff = now - start
    if current <= 0 or diff <= 0 or not total:
        # Nothing meaningful to show yet, and avoids dividing by zero below.
        # `total` can legitimately be 0/None when the size isn't known yet.
        return
    current += completed_bytes
    total += completed_bytes
    percentage = current * 100 / total
    speed = current / diff
    time_to_completion = round((total - current) / speed)
    progress_str = "[{0}{1}] {2}%".format(
        ''.join(["█" for i in range(math.floor(percentage / 5))]),
        ''.join(["░" for i in range(20 - math.floor(percentage / 5))]),
        round(percentage, 2))
    tmp = progress_str + "\n"
    tmp += f"{humanbytes(current)} of {humanbytes(total)}\n"
    tmp += f"Speed: {humanbytes(speed)}/s\n"
    tmp += f"ETA: {time_to_completion}s"
    try:
        await message.edit_text(text=tmp)
    except:
        pass

def humanbytes(size):
    # байты -> читаемый формат
    if not size:
        return ""
    power = 1024
    n = 0
    Dic_powerN = {0: "", 1: "KB", 2: "MB", 3: "GB", 4: "TB"}
    while size > power:
        size /= power
        n += 1
    return f"{round(size, 2)} {Dic_powerN[n]}"
