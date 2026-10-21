"""What a user can change about their downloads, and what they get by default.

Kept free of both SQLite and Pyrogram so the rules can be tested on their own.
The storage lives in `services/database.py`; the screens in `handlers/menu.py`.
"""

# --- quality -----------------------------------------------------------------
# "auto" is the owner's chosen default: the best quality that fits Telegram's
# 50 MB limit. A number caps the short side of the frame (see `quality_side`
# in handlers/youtube.py -- never the raw height, which reads vertical video as
# oversized). "ask" turns automatic sending off and always shows the picker.
QUALITY_AUTO = "auto"
QUALITY_ASK = "ask"

# --- audio -------------------------------------------------------------------
# YouTube serves an original track plus auto-dubs. "ru" prefers a Russian
# track, falling back to the original when there is none; "original" always
# takes the track the video was published with.
AUDIO_RU = "ru"
AUDIO_ORIGINAL = "original"

# --- groups ------------------------------------------------------------------
GROUPS_ON = "on"
GROUPS_OFF = "off"

DEFAULTS = {
    "quality": QUALITY_AUTO,
    "audio": AUDIO_RU,
    "groups": GROUPS_ON,
}

# Ordered so the settings screens can render buttons straight from here.
OPTIONS = {
    "quality": [
        (QUALITY_AUTO, "Максимальное (до 50 МБ)"),
        ("1080", "Не выше 1080p"),
        ("720", "Не выше 720p"),
        ("360", "Не выше 360p"),
        (QUALITY_ASK, "Всегда спрашивать"),
    ],
    "audio": [
        (AUDIO_RU, "Русская дорожка"),
        (AUDIO_ORIGINAL, "Язык оригинала"),
    ],
    "groups": [
        (GROUPS_ON, "Реагировать на мои ссылки"),
        (GROUPS_OFF, "Игнорировать мои ссылки"),
    ],
}

TITLES = {
    "quality": "Качество видео",
    "audio": "Язык звука",
    "groups": "Мои ссылки в группах",
}

HINTS = {
    "quality": (
        "Что присылать, когда качество можно выбрать автоматически. "
        "Больше качество — больше вес файла и дольше ожидание."
    ),
    "audio": (
        "У многих роликов YouTube есть оригинал и автодубляж. "
        "Если нужной дорожки нет, возьму оригинал."
    ),
    "groups": (
        "Отключи, если не хочешь, чтобы бот отвечал на твои ссылки в группах. "
        "В личке он продолжит работать."
    ),
}


def valid_values(key: str) -> list:
    return [value for value, _label in OPTIONS.get(key, [])]


def label_for(key: str, value: str) -> str:
    for candidate, label in OPTIONS.get(key, []):
        if candidate == value:
            return label
    return str(value)


def normalize(settings: dict | None) -> dict:
    """Fill in defaults and drop anything unrecognised.

    Stored rows outlive the code that wrote them: an option removed in a later
    version must not leave a user stuck on a value nothing handles any more.
    """
    result = dict(DEFAULTS)
    for key, value in (settings or {}).items():
        if key in DEFAULTS and value in valid_values(key):
            result[key] = value
    return result


def max_side_for(quality: str) -> int | None:
    """The `max_side` to pass to `best_stream_within_limit`.

    None means "no cap". `QUALITY_ASK` has no cap either -- it is handled
    before the automatic choice is made, by not making one.
    """
    if quality in (QUALITY_AUTO, QUALITY_ASK):
        return None
    try:
        return int(quality)
    except (TypeError, ValueError):
        return None


def should_auto_send(quality: str) -> bool:
    return quality != QUALITY_ASK


def audio_lang_for(audio: str) -> str:
    """Language code to prefer for the audio track.

    Empty disables the preference, which leaves `pick_audio_format` ranking by
    `language_preference` alone -- and that puts the original track first.
    """
    return "" if audio == AUDIO_ORIGINAL else audio


def reacts_in_groups(settings: dict | None) -> bool:
    return normalize(settings)["groups"] == GROUPS_ON
