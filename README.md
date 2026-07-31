# Telegram Video Downloader Bot

Async Telegram bot (Pyrogram) that downloads videos from **TikTok**, **YouTube**, **Instagram Reels**, and **Twitter/X**, and sends them straight into the chat.

Current version: see [`VERSION`](VERSION) / [`CHANGELOG.md`](CHANGELOG.md), or ask the bot itself with `/version`.

## Features

- **TikTok** — no-watermark video downloads via the tikwm.com API, plus **photo slideshows** (sent as a photo album)
- **YouTube** — video and Shorts via `yt-dlp`, with a quality picker (inline buttons, cancellable) for longer videos
- **Instagram Reels** — via `yt-dlp`, transcoded to H.264/AAC with `ffmpeg` for broad Telegram client compatibility
- **Twitter/X** — via `yt-dlp`
- **Multiple links in one message** — up to 5 processed per message, across all four platforms
- **YouTube playlists** — downloads the first video, then lets you step through the rest one at a time (`▶️ Следующее видео` / `❌ Хватит`) instead of dumping the whole thing at once
- **50 MB guard** — checked against Telegram's own bot upload limit both from provider metadata and, as a backstop, against the actual downloaded file size
- **Per-user download lock + rate limit** — one in-flight download per user per platform, plus a cooldown (`REQUEST_COOLDOWN_SECONDS`, default 5s) between requests to blunt rapid-fire spam
- **Global concurrency cap** — at most `MAX_CONCURRENT_DOWNLOADS` (default 2) downloads run at once across *all* users; the rest queue, so a busy moment can't spawn one `yt-dlp`/`ffmpeg` per user on a small box
- **Admin alerts** — download failures are posted to `ADMIN_ID`/`OWNER_ID` in real time, throttled per (platform, error type) so a burst of identical failures doesn't flood the chat
- **`/broadcast`** (admin-only) — message every registered user, with a per-message opt-out button and a delivery report (who got it, who didn't)
- **SQLite analytics** — tracks users, downloads, and errors; `/stats` (admin-only) shows totals, 24h activity, and 24h error rate per platform
- **Log rotation** — 10 MB per file, 5 backups
- **Self-healing in production** — systemd service + a timer-driven healthcheck monitor that restarts the bot and posts a Telegram alert on failure (see [`deploy/`](deploy/))
- **CI/CD** — every push runs the test suite, then deploys and healthchecks on a self-hosted GitHub Actions runner (see [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml))

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
| `ADMIN_ID` | one of these | Telegram user ID allowed to run `/stats` and `/broadcast` |
| `OWNER_ID` | one of these | Fallback for `ADMIN_ID` if it's unset |
| `WORKERS` | no | Pyrogram worker count |
| `CHANNEL_URL`, `BOT_URL` | no | Used in bot copy/links, not by core logic |
| `REQUEST_COOLDOWN_SECONDS` | no | Per-user cooldown between requests (default `5`) |
| `MAX_CONCURRENT_DOWNLOADS` | no | Downloads running at once across all users (default `2`) |
| `ERROR_REPORT_COOLDOWN_SECONDS` | no | Minimum gap between repeat admin error alerts (default `300`) |
| `COOKIES_B64` | no | Base64 `cookies.txt`, restored on startup by `start.sh`. Only relevant if you run via `start.sh`; the systemd deployment below reads `cookies.txt` directly from disk. |

Note: `ADMIN_ID` falls back to `OWNER_ID` only when `ADMIN_ID` is completely unset — an empty string does not count as "set" but does skip the fallback (see `services/utils/env.py`).

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

### CI/CD

Pushing to `master` runs the test suite on a GitHub-hosted runner, then — only if tests pass — pulls, restarts, and healthchecks the bot on a **self-hosted runner** living on the same box as the bot (needed because the server has no public IP; see `.github/workflows/deploy.yml`).

## Admin commands

Sent by the user in `ADMIN_ID`/`OWNER_ID`:

- `/stats` — user count, downloads and 24h error rate per platform
- `/broadcast <text>` — message every registered user; each message carries a `🔕 Больше не присылать рассылки` opt-out button, and the bot reports back exactly who received it and who didn't
- `/version` — also available to everyone, not just the admin

## Testing

```bash
pytest tests/ -v
```

Covers both the service layer (database, filename sanitizing, URL parsing, the four downloaders with network calls mocked) and the Telegram-facing handlers (locks, rate limiting, multi-link batching, playlists, error reporting, broadcast) using lightweight `pyrogram`-shaped test doubles — see `tests/_helpers.py`.

## Project structure

```
main.py                    entry point, Pyrogram client, /start, /stats, /broadcast, /version
handlers/                  one file per platform: Telegram-facing message/callback routing
handlers/base.py           shared lock/rate-limit/error-reporting/multi-link helpers
services/                  platform downloaders + shared utils, no Pyrogram dependency
services/database.py       SQLite analytics, playlist step-through state, broadcast subscriptions
services/utils/            filename sanitizing, cookies setup, progress bar, env/version/broadcast helpers
tests/                     pytest suite for both the services layer and the handlers
deploy/                    systemd units + healthcheck monitor for production
archive/                   retired files kept for reference — not used by the running bot
VERSION / CHANGELOG.md     current version and release history
```

See [`archive/README.md`](archive/README.md) for what's parked there and why.

## Known limitations

- The TikTok/YouTube/Instagram/Twitter handlers delete the user's original message with the link after a successful download — silently no-ops if the bot lacks delete rights in a group.
- YouTube playlist step-through processes at most 25 videos per playlist (`MAX_PLAYLIST_ITEMS` in `handlers/youtube.py`) — a deliberate cap, not a bug.
