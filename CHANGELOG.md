# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow [SemVer](https://semver.org/).

## [1.4.0] — 2026-08-04

Two bugs players hit within a day of the chain shipping, plus the content
that makes rarity mean something.

### Fixed
- **The event banner no longer stops the game or covers the board.** The
  pause existed for one narrow reason — mirror and reverse move everything
  somewhere else, and without a beat to re-read the board you die without
  knowing why — but it fired on every apple, so the run stuttered constantly.
  It now applies only to those two events, and the banner is a 24px line
  above the board rather than a card over the middle of it.
- **The pad no longer drops presses.** A single queued-direction slot meant
  two quick taps overwrote each other, and the U-turn check compared against
  the direction being travelled rather than the last one accepted, which
  discarded the second half of right → down → left. There is now a queue of
  two, consumed one per tick, with haptic feedback.
- **The board could silently stop being square.** `resize()` computed its
  size from `innerHeight - 398`, which goes negative on a short viewport; the
  browser discarded the invalid width and the canvas reverted to its 300×150
  default, no longer matching what the game thought it was drawing.

### Added
- **Five events, three of them legendary.** That tier previously held exactly
  one entry, so the rarest possible roll was always the same thing — a
  rarity system whose top prize is known in advance isn't one. Now: 🟢
  Блуждание, 🔵 Линька, 🟣 Замедление (the one event that helps), 🟡
  Нашествие, 🟡 Золотая лихорадка. Seventeen events in total.
- **A catalogue version**, sent with every result. A cached older build now
  gets "reopen the game" instead of being told its chain looks forged.
- **Versioned import URLs** in the client. A browser holding an old
  `chaos.js` beside a new `game.js` fails the module outright and shows a
  blank screen — worse than merely being out of date.

### Changed
- The daily post goes to people who have opened the game, not to every row in
  the users table. The first one failed for four of thirteen with
  PEER_ID_INVALID: they reached that table by dropping a link in a group the
  bot sits in, and Telegram does not let a bot open a private chat with
  someone who never started it. The HTTP Bot API returns "chat not found" for
  the same ids, so no change of transport helps — only the audience.

## [1.3.2] — 2026-08-04

### Fixed
- **Every attempt in a day replayed the same board.** Apple and wall
  placement was seeded from the day, like the event chain, so replaying the
  day rewarded memorising a route rather than playing. Only the chain has a
  reason to be fixed to the day; the world is now seeded per attempt.

## [1.3.1] — 2026-08-04

### Fixed
- **Leaderboard rows mixed data from different runs.** The query paired
  `MAX(score)` with bare columns and a second aggregate; SQLite only
  guarantees bare columns come from the max() row when a query has exactly
  one min()/max(). A player with a 500-point run of 30 apples and a
  100-point run of 2 could be shown "500 points, 2 apples" — a run that never
  happened. Replaced with a window function.

## [1.3.0] — 2026-08-04

The chain that the name promised. Clearing snake no longer ends the day — it
opens the next link.

### Added
- **«Слияние»**, the second game: slide tiles, equal ones merge, reach 128 to
  finish the chain. It reuses the existing pad, which maps onto the four
  directions exactly, and asks for planning rather than reflexes — a
  deliberate change of pace after the snake.
- **A daily modifier for it**, shared by everyone and drawn from the day seed:
  a second tile every move, a tile that freezes in place for six moves, or a
  board that rotates every fifth move.
- Runs that finish the chain are marked 🔗 in `/top`.

### Changed
- **Payload format v2**, carrying one entry per link. v1 is still accepted:
  a Mini App left open across a deploy keeps sending it, and rejecting those
  would look like the game silently eating results.
- `chaos_runs` gains `stages` and `chain_completed`, added by migration so the
  runs already recorded survive.

### Notes
- Clearing the day, and therefore the streak, still means seven apples in the
  snake. The second link adds score and a 🔗, and can be skipped — raising the
  bar would have retroactively broken streaks people already earned.
- The merge board is driven by the player's own moves, so unlike the snake
  chain there is nothing to replay it against. Its checks are a sanity net —
  score per move, a floor on human reaction time, and the daily modifier,
  which the bot re-derives independently.

## [1.2.0] — 2026-08-03

**Chaos Chain** — a daily game challenge, and the first thing in this bot
that isn't about downloading video. The point is a reason to open the bot
every day: a five-minute run whose rules keep changing under you.

### Added
- **Snake as a Telegram Mini App**, served from GitHub Pages out of `docs/`.
  No backend and no hosting cost: the result comes back to the bot as a
  `web_app_data` message and lands in SQLite.
- **A shared day.** Everything about today derives from a hash of its date,
  so every player gets the same chain of events and scores are worth
  comparing. The day turns over at noon Almaty rather than midnight.
- **Escalation through rarity.** The apple count doesn't pick the event, it
  shifts the odds toward rarer ones — one mechanic instead of two, and
  tension that climbs on its own.
- **Modifiers that stack** up to four at once, each one making an apple
  worth more, so playing it safe is never the winning strategy.
- `/chaos`, `/top`, `/streak`, and a daily post when the day turns over
  (which reuses the existing broadcast opt-out rather than adding a second
  setting to manage).

### Notes
- The download side is untouched: no handler, service or table of it was
  modified. The game keeps its own `chaos.db`, and `main.py` gained nine
  lines and lost none.
- The client computes its own score, so a determined player can lie about
  it. Validation rejects everything short of replaying the day's real event
  chain by hand, which is the right trade for an audience of a dozen.
- The PRNG exists twice, in Python and JavaScript. A test pins the Python
  side against chains generated by the real client under node — if they ever
  drift, every honest result would be rejected, so CI fails instead.

## [1.1.2] — 2026-08-03

### Fixed
- **A large YouTube video lost its link before it was ever downloaded.** Videos
  that need a quality picker returned `RESULT_PICKER`, and the handler treated
  anything that wasnt an outright failure as success — so the users message
  was deleted while the picker was still on screen. If they then cancelled, or
  chose a quality over the 50 MB limit, the link they needed to retry with was
  already gone. The source message is now removed only once a video has
  actually been sent.

## [1.1.1] — 2026-07-31

Cleanup of the loose ends left by the second audit.

### Fixed
- `progress()` no longer divides by zero when the total size is unknown
  (`total` of 0 or `None`) — previously only the caller's `if total:` check
  stood between it and a crash.
- The TikTok handler now carries the same `filters.group | filters.private`
  chat filter as the other three, instead of reacting in any chat type.

### Changed
- `tests/test_bot_start.py` now checks something real — that every handler and
  service module imports cleanly and exposes its entry point. It used to assert
  that env vars were set, which CI supplies itself, so it only ever confirmed
  that CI had run its own step.

### Removed
- Dead code: unused `elapsed_time`/`estimated_total_time` in `progress_bar.py`,
  and unused imports (`re` and `YTDownloadError` in `handlers/youtube.py`,
  `datetime` in `services/database.py`, `asyncio` in `tiktok_downloader.py`).
- A stray 14 MB `downloads/1` file left over from June.

## [1.1.0] — 2026-07-31

Hardening for the box the bot actually runs on (a phone with ~2 GB of RAM that
has already seen OOM kills).

### Added
- **Global concurrency cap** (`MAX_CONCURRENT_DOWNLOADS`, default 2). The
  per-user lock bounded nothing overall: N users meant N concurrent
  `yt-dlp`/`ffmpeg` processes. Downloads past the cap now queue instead.
- **Memory limits on the bot's systemd unit** — `MemoryHigh=600M` throttles it
  before `MemoryMax=800M` stops it, so the bot (and the ffmpeg children in its
  cgroup) can't starve the rest of the machine.

### Changed
- **CI no longer discards server-side edits silently.** `git reset --hard` was
  wiping any local changes to tracked files on every deploy; the workflow now
  stashes them first with a timestamped label and prints a warning.

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
