# Agent Instructions

## Scope

This repository is the production TikTok/YouTube/Instagram/Twitter downloader bot. Keep changes focused on the requested surface. Do not modify other workspaces.

Read the deployment details in [deploy/README.md](deploy/README.md) and [deploy/README_MONITORING.md](deploy/README_MONITORING.md) before changing systemd or monitoring.

## Current State (updated 2026-10-21)

Read this before planning: it records decisions and facts that the code and git
history do not show on their own.

- **Version 1.10.0.** The downloader runs in production on this box
  (`/home/droid/tiktokloaderhub_bot`), which is also the self-hosted Actions
  runner. There is no HTTP service any more.
- **Audio language.** `PREFERRED_AUDIO_LANG` (default `ru`) drives YouTube audio
  track choice in `services/youtube/youtube_downloader.py` via
  `pick_audio_format()`. Do not reintroduce a size-only `max()` there — that was
  the 1.6.5 bug. `language_preference` is 10 for an original track and -1 for an
  auto-dub; `language` may be regional (`ru-RU`), so match on a prefix.
- **Video quality.** `best_stream_within_limit()` in `handlers/youtube.py` sends
  the best quality whose known size fits `AUTO_SEND_MAX_BYTES` (the full 50 MB).
  Measure quality with `quality_side()` — `min(width, height)` — never with
  `height` alone: YouTube labels a format by its short side, so a height-based
  cap reads vertical video as oversized and was what pinned Shorts to 144p in
  1.6.6. Never auto-send a format with an undeclared filesize. `max_side` and
  `max_bytes` are the hooks for the planned per-user preset.
- **The Mini App was removed outright in 1.10.0** (owner decision), not
  rebuilt: the HTTP API, the static frontend, the `tiktokbot-api` unit, the
  Pages workflow and the `/app` command are all gone. The bot does its job in
  the chat, and a second delivery path earned maintenance without earning use.
  Do not reintroduce an HTTP surface without asking.
  **Tailscale Funnel is shared with another project**: `/` used to proxy the
  removed API on 8081, but `/olx` proxies a different bot on 5051. Never turn
  Funnel off wholesale.
- **Controls and settings shipped in 1.8.0.** `handlers/menu.py` owns the
  persistent reply keyboard, the settings screens and the `/settings` and
  `/help` commands; `services/user_settings.py` holds the options, defaults and
  validation, free of both SQLite and Pyrogram; `services/database.py` stores
  them. Read preferences through `user_settings.normalize()` and never trust a
  value straight from the table or from a callback payload — both outlive the
  code that wrote them. New settings belong in `OPTIONS`/`TITLES`/`HINTS`
  together, since the screens render from them. The command menu is published
  in `_run_bot()`; keep admin-only commands off it.
- **The support channel shipped in 1.9.0.** `services/support.py` holds the
  statuses, limits and report validation; `handlers/support.py` owns the flows;
  tickets, replies, the last-failure context and "the next message means
  something" all live in `services/database.py`. Two invariants: an admin reply
  is addressed from the ticket row and never from the callback payload, and
  every admin action re-checks the sender against `ADMIN_ID`. The pending-input
  catcher runs in handler group `-1` and raises `StopPropagation`, so a message
  written as a report never also reaches the platform handlers.

### Settled: the member's choice wins in groups

"Ignore my links in groups" cannot be overridden by a group admin (owner
decision, 2026-10-21). This is deliberate, not a missing feature: the setting
governs that person's own messages, so letting someone else switch it back on
would make the bot act on their links against an explicit request. It also
keeps group handling free of a per-message admin-rights lookup. The cost is
accepted — to the rest of a group the bot simply looks silent for one person,
and the person who set it can see it in their own settings.

### Telegram command menus

Telegram stores a command list per **scope and per language**, and a private
chat resolves them chat → chat_member → all_chat_administrators →
all_private_chats → default. Setting the default scope alone changes nothing
for anyone a narrower scope covers, and within one scope a language-specific
list outranks the neutral one. Deleting a command from the code does not
unregister it anywhere. `_publish_command_menu()` in `main.py` clears the
localized copies of every scope it writes, empties the scopes meant to fall
through, and only then sets the lists; verify a change with `getMyCommands`
across *all* scopes and languages, never just the default. Clients also cache
the list, so a correct server-side menu can still look stale for a while.

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

- `main.py` creates the Pyrogram client, database and command handlers, and publishes the command menu from `_run_bot()` once the client is connected.
- `handlers/menu.py` is the only place that draws the keyboard or the settings screens; `handlers/base.ignores_links_in_groups` is the shared guard every platform handler calls first.
- `handlers/` adapts Pyrogram messages/callbacks to the platform services. Do not call these handlers from HTTP code.
- `services/downloader.py` is the Pyrogram-free platform dispatcher. Provider implementations live under `services/tiktok/`, `services/youtube/`, `services/instagram/`, and `services/twitter/`.

## Secrets and Runtime Data

Never commit or print `.env`, `cookies.txt`, `COOKIES_B64`, Telegram tokens, API hashes, databases, encryption keys, downloads, or logs. Cookies are optional for public YouTube downloads but improve YouTube/Instagram reliability when present.

## Systemd and Deployment

- `tiktokbot.service` runs the bot; `tiktokbot-monitor.timer` checks it through the project healthcheck.
- Production runs on a self-hosted ARM64 GitHub Actions runner with labels `self-hosted`, `Linux`, and `ARM64`.
- `.github/workflows/deploy.yml` tests first, then deploys only pushes to `master`, updates `/home/droid/tiktokloaderhub_bot`, restarts `tiktokbot.service`, and runs `healthcheck.py`.
- Do not put secrets in unit files or workflow YAML. Preserve the workflow's protection against unreported local tracked edits.

Useful checks:

```bash
sudo systemctl is-active tiktokbot.service tiktokbot-monitor.timer
sudo journalctl -u tiktokbot.service -n 80 --no-pager
./venv/bin/python healthcheck.py
```
