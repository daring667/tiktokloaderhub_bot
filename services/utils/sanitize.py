"""Utility for making safe filenames from video titles."""
import re
import unicodedata


def sanitize_filename(name: str, maxlen: int = 120) -> str:
    """Make a safe filename from a title: strip invalid chars and trim length."""
    if not name:
        return "video"

    # Normalize Unicode to remove combining chars
    name = unicodedata.normalize('NFKD', name)
    # Remove filesystem-invalid characters
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    # Trim length
    if len(name) > maxlen:
        name = name[:maxlen].rstrip()
    return name
