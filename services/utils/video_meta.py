"""Video dimensions for Telegram uploads.

Pyrogram does not work these out on its own, and `send_video` without them
tells Telegram the video is 0x0. Clients then guess the aspect ratio, which
renders a vertical video squashed into a landscape box.
"""
import json
import logging
import subprocess


def probe_video_metadata(path: str) -> dict:
    """Return ``{"width", "height", "duration"}`` for *path*, as far as known.

    Never raises: a missing ffprobe or an unreadable file costs the aspect
    hint, not the upload. Keys whose value could not be determined are left
    out, so the result can be splatted straight into ``send_video``.
    """
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=width,height:stream_side_data=rotation:format=duration",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        info = json.loads(out)
    except Exception as e:
        logging.warning("ffprobe failed for %s: %s", path, e)
        return {}

    streams = info.get("streams") or []
    if not streams:
        return {}
    stream = streams[0]

    width = stream.get("width")
    height = stream.get("height")

    # A phone recording is often stored landscape with a rotation matrix. The
    # player honours it, so the dimensions Telegram needs are the swapped ones.
    rotation = 0
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            try:
                rotation = int(side["rotation"])
            except (TypeError, ValueError):
                rotation = 0
            break
    if rotation % 180 != 0:
        width, height = height, width

    result = {}
    if width and height:
        result["width"] = int(width)
        result["height"] = int(height)

    duration = (info.get("format") or {}).get("duration")
    if duration is not None:
        try:
            seconds = int(float(duration))
        except (TypeError, ValueError):
            seconds = 0
        if seconds > 0:
            result["duration"] = seconds

    return result
