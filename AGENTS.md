# Agent Instructions

## Scope

This repository is the production TikTok/YouTube/Instagram/Twitter downloader bot plus a separate downloader Mini App API and static frontend. Keep changes focused on the requested surface. Do not modify other workspaces.

Read the deployment details in [deploy/README.md](deploy/README.md), [deploy/README_MONITORING.md](deploy/README_MONITORING.md), and [deploy/MINIAPP_SETUP.md](deploy/MINIAPP_SETUP.md) before changing systemd, monitoring, or Mini App hosting.

## Current State (updated 2026-10-21)

Read this before planning: it records decisions and facts that the code and git
history do not show on their own.

- **Version 1.6.5.** The downloader, the Mini App API, and the static frontend
  are in production on this box (`/home/droid/tiktokloaderhub_bot`), which is
  also the self-hosted Actions runner.
- **Audio language.** `PREFERRED_AUDIO_LANG` (default `ru`) drives YouTube audio
  track choice in `services/youtube/youtube_downloader.py` via
  `pick_audio_format()`. Do not reintroduce a size-only `max()` there — that was
  the 1.6.5 bug. `language_preference` is 10 for an original track and -1 for an
  auto-dub; `language` may be regional (`ru-RU`), so match on a prefix.
- **Chaos Chain is slated for full removal** (owner decision, 2026-10-21): every
  game, leaderboard, and streak surface comes out rather than staying behind
  `CHAOS_ENABLED=0`. Affected: `handlers/chaos.py`, `services/chaos/`,
  `docs/chaos.js`, `docs/game.js`, `docs/merge.js`, `docs/style.css`,
  `docs/index.html`, the `chaos_*` wiring in `main.py`, and five test modules.
  Keep `chaos.db` on disk; it holds real player history and is gitignored.
- **The Mini App is being rebuilt from scratch** (owner decision, 2026-10-21).
  `TODO.md` is the live roadmap for the cabinet (Download / History / Profile).
  `api/history.py` is already written but **untracked and not wired up** — it is
  groundwork for that roadmap, not dead code; do not delete it, and do not
  assume it runs. The current frontend advertises only TikTok and YouTube even
  though the bot supports Instagram and Twitter as well.
- **Bot controls are being reworked** to a persistent reply keyboard plus a
  BotFather command menu (owner decision, 2026-10-21). Today there is no button
  surface at all — only slash commands.
- **A support channel is planned**: an inline button on a user-facing error that
  opens a report, delivery of that report to the admin, and an admin reply sent
  back to that specific user as the bot. Nothing of this exists yet.

### Deployment reality

- **This box cannot push to GitHub.** There is no `gh`, no credential helper, no
  `~/.git-credentials`, and no private SSH key for GitHub — `~/.ssh` holds only
  `authorized_keys`. Commits land locally; pushing (and therefore the CI deploy)
  has to happen from somewhere that has credentials, or after a deploy key is
  installed here. Do not try to supply a token.
- Because the box *is* production, editing files here and restarting the unit
  makes a change live immediately, without CI. Leaving tracked edits
  uncommitted will fight the next CI deploy — commit them.
- `.env` backups live in `~/env-backups` (mode 600), outside the repo.

## Validation Commands

Use the project virtual environment:

```bash
./venv/bin/python -m pytest tests/ -q
./venv/bin/python -m pytest tests/test_api.py -q
./venv/bin/python -m py_compile api/*.py main.py
./venv/bin/python healthcheck.py
```

`ffmpeg` is required for media processing. The full suite should pass before a commit. A single deprecation warning about the pytest event loop may remain; do not hide real failures behind it.

## Architecture Boundaries

- `main.py` creates the Pyrogram client, database, command handlers, Mini App `/app` button, and optional Chaos registration.
- `handlers/` adapts Pyrogram messages/callbacks to the platform services. Do not call these handlers from HTTP code.
- `services/downloader.py` is the Pyrogram-free platform dispatcher. Provider implementations live under `services/tiktok/`, `services/youtube/`, `services/instagram/`, and `services/twitter/`.
- `api/auth.py` validates Telegram Web App `initData`; never trust a frontend-supplied user ID or bypass this check.
- `api/jobs.py` owns bounded Mini App jobs, file limits, cleanup metadata, and Telegram Bot API delivery. Jobs are currently in memory and disappear when the API restarts.
- `api/app.py` exposes the authenticated job API and admin summary. `api/server.py` is the API entrypoint.
- `docs/downloader.*` is the downloader Mini App. The existing Chaos files in `docs/` and `services/chaos/` are a separate feature.

## Mini App Rules

- The Mini App must be opened from Telegram so `Telegram.WebApp.initData` exists. Direct browser opening is intentionally unauthenticated.
- Keep the API behind HTTPS; production currently uses Tailscale Funnel and the API listens locally on port 8081.
- Keep `MINIAPP_ALLOWED_ORIGIN` set to the exact HTTPS GitHub Pages origin, never `*` in production.
- Completed media should normally be sent by the API through Telegram Bot API. Do not regress to unauthenticated `blob:` or direct filesystem URLs.
- When changing frontend assets, update the cache-busting query/version used by the `/app` URL and test the actual published Pages path.
- Keep ownership checks on every job status, cancel, and file endpoint.

## Secrets and Runtime Data

Never commit or print `.env`, `cookies.txt`, `COOKIES_B64`, Telegram tokens, API hashes, databases, encryption keys, downloads, or logs. Cookies are optional for public YouTube downloads but improve YouTube/Instagram reliability when present. Telegram file delivery requires the user to have opened the bot and the API process to have `BOT_TOKEN`.

## Chaos Chain

Chaos Chain is paused by default with `CHAOS_ENABLED=0` and is not registered by `main.py` unless explicitly enabled. Keep it separate from downloader and Mini App changes. If modifying it, update the Python and JavaScript contracts together and run the Chaos tests; do not reorder its event catalogue.

## Systemd and Deployment

- `tiktokbot.service` runs the bot; `tiktokbot-api.service` runs `python -m api.server`; `tiktokbot-monitor.timer` checks the bot through the project healthcheck.
- The API unit is installed separately from the bot monitor; verify both when changing Mini App/API code.
- Production runs on a self-hosted ARM64 GitHub Actions runner with labels `self-hosted`, `Linux`, and `ARM64`.
- `.github/workflows/deploy.yml` tests first, then deploys only pushes to `master`, updates `/home/droid/tiktokloaderhub_bot`, restarts `tiktokbot.service`, and runs `healthcheck.py`.
- `.github/workflows/pages.yml` publishes `docs/` independently through GitHub Pages.
- Do not put secrets in unit files or workflow YAML. Preserve the workflow's protection against unreported local tracked edits.

Useful checks:

```bash
sudo systemctl is-active tiktokbot.service tiktokbot-api.service tiktokbot-monitor.timer
sudo journalctl -u tiktokbot.service -n 80 --no-pager
sudo journalctl -u tiktokbot-api.service -n 80 --no-pager
curl http://127.0.0.1:8081/api/health
```
