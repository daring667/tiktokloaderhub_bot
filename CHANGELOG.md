# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow [SemVer](https://semver.org/).

## [1.0.1] — 2026-07-31

Bug-fix release: everything here came out of a second full audit of the codebase.

### Fixed
- **Error messages were deleted before the user could read them.** In the TikTok,
  Instagram and Twitter handlers the error text was written into the status
  message, and then `finally` deleted that same message unconditionally — so a
  failed download looked like the bot had silently ignored the request. The
  status message is now only cleared on success. Affected every failure mode:
  the 50 MB limit, API errors, timeouts, HTTP errors.
- **The playlist "next video" button was rate-limited.** The 5s per-user cooldown
  applied to a button the user is *meant* to press immediately after the previous
  download. `download_slot` now takes `enforce_cooldown`, and the button skips the
  cooldown while still respecting the "no concurrent downloads" lock.
- **The playlist replied to a message it had already deleted.** The prompt is now
  removed after the next video has been sent, not before.
- **The quality picker and the "next video?" prompt appeared at the same time**,
  about two different videos. The next video is now offered only once the current
  one is actually finished — including after the user picks a quality, which is
  tracked by tying the picker to the playlist session.
- **Instagram and Twitter never deleted the user's source message**, unlike TikTok
  and YouTube, because their handlers didn't report success back to the caller.
  All four platforms now behave the same way.
- **Abandoned callback tokens and playlist sessions accumulated forever** — they
  were only deleted on the happy path. Stale rows are now swept on startup
  (`cleanup_stale_state`, 24h by default).

## [1.0.0] — 2026-07-29

First versioned release — everything below shipped in one continuous push from an
unversioned, security-compromised state to a tested, monitored, feature-complete bot.

### Added
- **Twitter/X support** via `yt-dlp`
- **Multiple links per message** (up to 5), across TikTok/YouTube/Instagram/Twitter
- **YouTube playlists** — downloads the first video, then offers to step through the
  rest one at a time (`▶️ Следующее видео` / `❌ Хватит`) instead of dumping the whole
  thing at once
- **Cancel button** on the YouTube quality picker
- **TikTok photo slideshows** — sent as a Telegram photo album (chunked at 10 per
  album) instead of silently downloading the background music as if it were a video
- **Per-user rate limiting** — a cooldown (`REQUEST_COOLDOWN_SECONDS`, default 5s)
  between requests, on top of the existing "no concurrent downloads" lock
- **Real-time admin error alerts** — download failures are posted to
  `ADMIN_ID`/`OWNER_ID` immediately, throttled per (platform, error type) so a burst
  of identical failures doesn't flood the chat; every failure is also logged to the
  database regardless of whether the alert itself was throttled
- **`/broadcast`** admin command — messages every registered user, with a per-message
  `🔕 Больше не присылать рассылки` opt-out button and a delivery report naming who
  did and didn't receive it
- **`/stats`** now shows 24h error rate per platform, alongside download totals
- **`/version`** command
- Self-hosted GitHub Actions runner + CI/CD: every push runs the test suite, then
  deploys and healthchecks the bot for real (not just "is the process alive")
- systemd deployment (`tiktokbot.service` + `tiktokbot-monitor.timer`), replacing
  ad-hoc manual runs
- Full test suite for the Telegram-facing handlers (locks, rate limiting, multi-link
  batching, playlists, error reporting, broadcast) — previously only the service
  layer was covered

### Changed
- YouTube quality picker switched to HTML formatting — fixes video titles containing
  markdown-special characters (`_`, `*`, etc.) breaking the rendered message
- Duration now shown as `mm:ss` instead of raw seconds
- Handler cleanup logic (temp files, status messages, download locks) consolidated
  into shared helpers in `handlers/base.py` instead of being duplicated per platform

### Fixed
- 50 MB size limit is now enforced against the actual downloaded file size as a
  backstop, not just provider-supplied metadata (which is sometimes missing)
- TikTok handler now has the same per-user concurrency lock the other platforms
  already had
- YouTube handler no longer silently logs a failed send as a successful download
- Stale deploy scripts pointing at servers/users that no longer exist replaced with
  ones matching the actual production host

### Security
- Removed a leaked SSH private key and session cookies from git history; secrets are
  no longer tracked in the repository
- Production deploys now use a repo-scoped SSH deploy key instead of a personal key
