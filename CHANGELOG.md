# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow [SemVer](https://semver.org/).

## [1.10.0] — 2026-10-21

### Removed
- **The downloader Mini App, outright.** Not rebuilt — removed (owner
  decision). Gone: the HTTP API (`api/`), the static frontend (`docs/`), the
  `tiktokbot-api` systemd unit, the GitHub Pages workflow, the `/app` command,
  the Mini App keyboard button and the `MINIAPP_*` settings. The bot already
  does its whole job inside the chat; a second delivery path meant a second
  thing to authenticate, host, expose over HTTPS and keep in sync, and it was
  earning maintenance without earning use.

  The planned cabinet rewrite (Download / History / Profile) went with it,
  including the unused `api/history.py` groundwork.

  **Tailscale Funnel was deliberately left alone.** Its `/` route proxied the
  removed API on port 8081, but `/olx` proxies an unrelated project on 5051, so
  turning Funnel off would have broken a different bot. The dead `/` route is
  harmless, and removing it is a separate, manual decision.

## [1.9.0] — 2026-10-21

### Added
- **A support channel.** When a download fails, the bot offers a button to
  describe what happened. The report becomes a numbered ticket delivered to the
  admin with the context already attached — platform, link and exception type
  — so nobody has to ask "which link was it?". The admin can answer from the
  ticket card, and the reply arrives in the reporter's own chat as a message
  from the bot. Statuses (разбираюсь / исправлено / закрыт) notify the reporter on
  their own. `/report` opens a report at any time; `/tickets` lists the open
  ones for the admin.

  Details that matter more than they look:
  - **Who receives an admin reply is read from the ticket row, never from the
    callback payload.** A payload can be replayed with an edited id, and the
    bot must not become a way to message an arbitrary user.
  - Every admin action re-checks the sender against `ADMIN_ID`: a button can be
    pressed by anyone who can see the message carrying it.
  - The failure context is remembered on **every** error, while the admin
    alert stays throttled — a burst of identical failures should not flood the
    admin, but the person in front of the error still needs the button.
  - The offer itself is throttled per user, or a message with five bad links
    would produce five identical offers.
  - "The next message is a report" lives in the database, not in memory, so a
    restart mid-typing does not swallow what someone is about to send.
  - A person may hold a few open tickets at once; the limit counts open
    tickets rather than a time window, so a real problem is never timed out.

### Changed
- `report_error` takes the user's message, which is what lets the offer appear
  next to the failure. In group chats it stays silent: a support offer aimed at
  one person is noise for everyone else, and `/report` still works in private.

## [1.8.1] — 2026-10-21

### Fixed
- **The command menu still listed the games.** `/chaos`, `/top` and `/streak`
  kept appearing after the code behind them was deleted, and the new `/settings`
  and `/help` never showed up. Publishing had only written the default scope.
  Telegram keeps a separate command list per scope *and* per language, and a
  private chat resolves them chat → chat_member → all_chat_administrators →
  all_private_chats → default, so lists written long ago into narrower scopes
  outranked the one being set. A per-chat list for the owner held all seven old
  commands, which is exactly what their menu showed; three other scopes held an
  older three-command list that everyone else saw. The menu is now published
  across every scope that can shadow it, with the localized copies cleared
  first, since a language-specific list outranks the neutral one within the
  same scope.
- **Group menus no longer advertise private-only commands.** Group chats get
  `/start`, `/help` and `/version`; `/settings` and `/app` only answer in
  private.

### Changed
- **The admin keeps their own menu.** `/stats` and `/broadcast` are published
  to the owner's own chat rather than being dropped, so they stay off the
  public list without disappearing for the person who uses them.

## [1.8.0] — 2026-10-21

### Added
- **A menu that stays on screen.** The bot had no button surface at all —
  every action was a typed slash command, and nothing advertised that the
  commands existed. There is now a persistent reply keyboard with the Mini App,
  the settings and help on it. The Mini App sits on a `web_app` button, so it
  opens on the first tap instead of costing a round trip through the bot. The
  keyboard is only sent in private chats: Telegram shows one reply keyboard per
  chat, and pushing ours into a group would replace whatever that group already
  uses, for everyone in it.
- **A published command menu.** `/start`, `/settings`, `/help`, `/app` and
  `/version` now appear in Telegram's own command list. `/stats` and
  `/broadcast` are deliberately left off: listing them invites people to try
  them and be told they have no access.
- **Per-user settings**, stored in `user_settings` and read on every link:
  - *Quality* — the best that fits 50 MB (the default), a cap of 1080p, 720p
    or 360p, or "always ask", which turns the automatic choice off and shows
    the picker instead.
  - *Audio language* — a Russian track where one exists, or always the
    original. "Original" drops the language filter entirely, which leaves
    `language_preference` to decide, and that favours the published track.
  - *My links in groups* — off means the bot ignores that person's links in
    group chats while continuing to work for them in direct messages.

  Unknown or retired values fall back to the defaults when read, so a row that
  outlives the option it names cannot strand a user on a dead setting. A
  database failure falls back to the defaults too: preferences are not worth
  refusing a download over.

### Changed
- `PREFERRED_AUDIO_LANG` is now the default rather than the rule. A user's own
  choice wins; the environment variable decides for anyone who has not picked.
- The Mini App URL is resolved in one place (`get_miniapp_url`). It carries a
  cache-busting version in its query string, so two copies of the string would
  drift apart the first time one was bumped.

## [1.7.1] — 2026-10-21

### Fixed
- **Videos no longer arrive squashed.** Reported for a vertical Shorts that
  Telegram drew into a landscape box. The downloaded file was never at fault:
  it measured 720x1280 with square pixels, a 9:16 display aspect and no
  rotation tag. The loss happened on the way out — `send_video` was called
  without `width`, `height` or `duration`, Pyrogram does not work them out on
  its own, so Telegram recorded the video as 0x0 and clients were left to guess
  the shape. A new `probe_video_metadata()` reads the three values with
  `ffprobe` and passes them along. It also honours a rotation matrix, since a
  phone recording is often stored landscape with a quarter turn attached.
  Applied to all four platforms: the same call was missing the same arguments
  in the TikTok, Instagram and Twitter handlers too.

  The helper never raises. If `ffprobe` is missing or the file is unreadable it
  returns nothing at all, costing the aspect hint rather than the upload.

## [1.7.0] — 2026-10-21

### Removed
- **Chaos Chain and every game surface.** The daily snake challenge, the merge
  stage, the leaderboard, the streaks and the `/chaos`, `/top` and `/streak`
  commands are gone rather than left paused behind `CHAOS_ENABLED=0`. The bot
  is a downloader; a second product living inside it earned its own
  maintenance burden on every change — two event catalogues that had to stay
  byte-identical across Python and JavaScript, their contract test, and a
  branch in `main.py` guarding code nobody ran.
  Deleted: `handlers/chaos.py`, `services/chaos/`, `docs/chaos.js`,
  `docs/game.js`, `docs/merge.js`, `docs/style.css` and six test modules, plus
  the `CHAOS_*` settings from `.env.example` and the systemd unit.
  `chaos.db` is deliberately kept on disk: it holds real player history, it is
  gitignored, and nothing reads it any more.

  The frontend half was already dead — `docs/index.html` had been reduced to a
  redirect to the downloader, so the game had no entry point, and nothing
  referenced `docs/style.css` at all.

## [1.6.6] — 2026-10-21

### Fixed
- **Shorts are no longer sent at 144p.** Reported as "Shorts arrive in bad
  quality", and it was worse than it sounded: a 55-second Shorts went out at
  144p while its 1080p50 version weighed 21.7 MB, well under half of Telegram's
  50 MB limit. Two things combined. The automatic choice ran before the quality
  picker, so the user never saw an alternative; and it capped quality by
  comparing a 360 limit against the frame *height*. YouTube names a format
  after its **short** side, so a vertical 360p frame is 360x640 — every Shorts
  quality failed that test except 144p, whose 144x256 slipped under it.
  Horizontal video was unaffected, since there the height *is* the short side,
  which is why this went unnoticed. Quality is now measured as
  `min(width, height)`, and `width` is carried through to the stream list,
  where it was previously dropped.
- **The quality cap no longer throws away headroom.** Instead of a fixed 360p
  ceiling the bot now sends the best quality whose **known** size fits the 50 MB
  budget. A format whose size YouTube did not declare is still never chosen
  automatically — that is what the picker is for, and an undeclared adaptive
  track is exactly how a 354 MB download once disguised itself as an 8 MB one.
  A stream of unknown dimensions is skipped too, since it cannot be ranked.

### Changed
- **The quality picker is now a fallback rather than the default.** When sizes
  and dimensions are known the best fitting quality is sent straight away. The
  picker still appears when nothing can be ranked or nothing fits, and a
  per-user preset will be able to narrow the cap or switch automatic sending
  off entirely (`max_side` and `max_bytes` on `best_stream_within_limit` are
  the hooks; `AUTO_SEND_MAX_BYTES` is the default budget).

## [1.6.5] — 2026-10-21

### Fixed
- **YouTube downloads no longer pick the audio track at random.** YouTube now
  ships one video with an original track plus auto-dubs in other languages, and
  the adaptive picker selected audio with `max(..., key=filesize)` — language
  was never part of the decision, so whichever track happened to encode largest
  won. On a Russian original whose English auto-dub came out 1.5 KB bigger
  (`140-0` en-US 890305 vs `140-1` ru 888803) the bot delivered English audio
  for a video that plays Russian on YouTube, which is exactly how it was
  reported. Selection is now language-first: tracks matching
  `PREFERRED_AUDIO_LANG`, then the original ahead of a dub of the same language,
  then m4a/AAC ahead of webm/opus because Telegram clients handle it better,
  and only then size.
- **A dub can now actually reach the file.** A progressive format (video and
  audio in one file) exists only with the original track, so when the wanted
  language is available only as a separate dubbed track the adaptive path is
  forced. When the original already is the wanted language the progressive
  single-file download is kept, since there is nothing to gain by splitting it.
- **`.env.bak*` was not gitignored.** Nothing had committed one yet, but the
  pattern was one careless `cp` away from putting tokens in history.

### Added
- **`PREFERRED_AUDIO_LANG`** (default `ru`) — which audio language to prefer on
  YouTube. Empty restores yt-dlp's own choice. The MP3 option honours it too,
  through a selector that falls back from the resolved format id to a language
  filter to the default, because format ids differ between `player_client`
  fallbacks.

## [1.6.4] — 2026-08-17

### Added
- **Group `@all` mentions.** A group administrator can write `@all` followed
  by a message; the bot replies with real clickable mentions of all non-bot
  participants. Large groups are split into safe-sized batches. The feature is
  limited to administrators and one use per minute per chat.

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
