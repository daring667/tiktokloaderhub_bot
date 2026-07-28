# Telegram Video Downloader Bot

Async Telegram bot (Pyrogram) that downloads videos from **TikTok**, **YouTube**, and **Instagram Reels** and sends them straight into the chat.

## Features

- **TikTok** — no-watermark downloads via the tikwm.com API
- **YouTube** — video and Shorts via `yt-dlp`, with a quality picker (inline buttons) for longer videos
- **Instagram Reels** — via `yt-dlp`, transcoded to H.264/AAC with `ffmpeg` for broad Telegram client compatibility
- **50 MB guard** — checked against Telegram's own bot upload limit both from provider metadata and, as a backstop, against the actual downloaded file size
- **Per-user download lock** — one in-flight download per user per platform, to avoid pile-ups from spammed links
- **SQLite analytics** — tracks users and downloads; `/stats` (admin-only) shows totals and 24h activity
- **Log rotation** — 10 MB per file, 5 backups
- **Self-healing in production** — systemd service + a timer-driven healthcheck monitor that restarts the bot and posts a Telegram alert on failure (see [`deploy/`](deploy/))

## Requirements

- Python 3.10+ (production runs 3.13)
- `ffmpeg` on PATH (`sudo apt install ffmpeg`) — needed by `yt-dlp` for merging/transcoding
- A `cookies.txt` (Netscape format) for YouTube/Instagram — without it YouTube requests are much more likely to be rate-limited or blocked

## Setup

```bash
git clone <this repo> TT && cd TT
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in the values below
```

### Environment variables (`.env`)

| Variable | Required | Notes |
|---|---|---|
| `API_KEY` | yes | Pyrogram `api_id`, from [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | yes | Pyrogram `api_hash`, from the same place |
| `BOT_TOKEN` | yes | From [@BotFather](https://t.me/BotFather) |
| `ADMIN_ID` | one of these | Telegram user ID allowed to run `/stats` |
| `OWNER_ID` | one of these | Fallback for `ADMIN_ID` if it's unset |
| `WORKERS` | no | Pyrogram worker count |
| `CHANNEL_URL`, `BOT_URL` | no | Used in bot copy/links, not by core logic |
| `COOKIES_B64` | no | Base64 `cookies.txt`, restored on startup by `start.sh`. Only relevant if you run via `start.sh`; the systemd deployment below reads `cookies.txt` directly from disk. |

Note: `ADMIN_ID` is read with `os.getenv("ADMIN_ID", os.getenv("OWNER_ID", "0"))` — the fallback only kicks in when `ADMIN_ID` is completely unset, not when it's set to an empty string.

### Cookies

Place a Netscape-format `cookies.txt` in the project root (same directory as `main.py`). YouTube and Instagram downloaders both fall back to cookie-less requests with alternate User-Agents if the file is missing or stale, but success rates drop noticeably.

## Running

### Locally / manually

```bash
./start.sh
```

### Production (systemd, no Docker)

The bot runs as a plain systemd service — see **[`deploy/`](deploy/)** for the full guide. Short version:

```bash
sudo bash deploy/setup_monitoring.sh
```

This installs `tiktokbot.service` (the bot) plus `tiktokbot-monitor.timer` (a 5-minute healthcheck that restarts the bot and pings you on Telegram if it stops actually working — not just if the process dies).

## Analytics & `/stats`

`bot_database.db` (SQLite, gitignored) tracks registered users and every successful download per platform. Send `/stats` as the user in `ADMIN_ID`/`OWNER_ID` to see totals, per-platform breakdown, and 24h activity.

## Testing

```bash
pytest tests/ -v
```

Covers the service layer — database, filename sanitizing, URL parsing, and the three downloaders (network calls mocked). The Telegram-facing handlers (`handlers/`, `main.py`) aren't covered yet.

## Project structure

```
main.py                    entry point, Pyrogram client, /start and /stats
handlers/                  one file per platform: Telegram-facing message/callback routing
services/                  platform downloaders + shared utils, no Pyrogram dependency
services/database.py       SQLite analytics
services/utils/            filename sanitizing, cookies setup, progress bar
tests/                     pytest suite for the services layer
deploy/                    systemd units + healthcheck monitor for production
archive/                   retired files kept for reference — not used by the running bot
```

See [`archive/README.md`](archive/README.md) for what's parked there and why.

## Known limitations

- The TikTok/YouTube/Instagram handlers delete the user's original message with the link after a successful download — silently no-ops if the bot lacks delete rights in a group.
- The `.github/workflows/deploy.yml` CI pipeline predates the current server layout and needs to be rewired (path/user/target host) before it can be trusted again — not yet done.
