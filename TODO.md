# TODO — Mini App Cabinet (Downloader + History + Profile)

- [ ] Add persistent SQLite table for Mini App download history.
- [ ] Record successful Mini App deliveries with user ID, platform, URL, title, timestamp, delivery status, and safe error code.
- [ ] Add `GET /api/me/summary` with total downloads, platform counts, last activity, and active job.
- [ ] Add `GET /api/me/history?limit=50` with owner-scoped records and pagination-ready response.
- [ ] Add `POST /api/me/history/{history_id}/retry` that creates a new owned download job.
- [ ] Enforce Telegram `initData` ownership on summary, history, retry, and history cleanup endpoints.
- [ ] Add tests for persistence across API restart, ordering, empty history, ownership, retry isolation, and delivery status.
- [ ] Build Mini App navigation: Download, History, Profile.
- [ ] Add profile card with Telegram name/avatar, total downloads, platform breakdown, and last activity.
- [ ] Add history cards with platform, title/URL, timestamp, status, copy link, and Download Again action.
- [ ] Add filters for All, TikTok, and YouTube, plus search by title or URL.
- [ ] Add loading skeletons, empty state, offline state, failed delivery state, and expired result state.
- [ ] Keep active download visible while switching cabinet sections.
- [ ] Keep successful delivery wording focused on video sent to Telegram chat; keep direct file download fallback authenticated.
- [ ] Add cache-busting for every frontend asset update and verify the published GitHub Pages URL.
- [ ] Run API tests and the full pytest suite.
- [ ] Manually verify: download, receive Telegram video, reopen Mini App, view history, retry download.
- [ ] Commit and push only TikTok repository changes.

## Remove the games (owner decision, 2026-10-21)

- [ ] Drop `handlers/chaos.py`, `services/chaos/`, and the `chaos_*` wiring plus
      daily announcer in `main.py`.
- [ ] Drop `docs/chaos.js`, `docs/game.js`, `docs/merge.js`, and the game-only
      parts of `docs/index.html` and `docs/style.css`.
- [ ] Drop `tests/test_chaos_*.py` and `tests/test_handlers_chaos.py`.
- [ ] Drop `CHAOS_*` from `.env`, `.env.example`, README, and AGENTS.md.
- [ ] Keep `chaos.db` on disk as player history; it is gitignored.
- [ ] Remove `/chaos`, `/top`, and `/streak` from the BotFather command list.

## Bot controls: persistent menu (owner decision, 2026-10-21)

- [ ] Add a reply keyboard shown from `/start` and kept across interactions.
- [ ] Register a BotFather command menu matching the surviving commands.
- [ ] Add a per-user settings surface: audio language, default quality,
      video vs MP3.
- [ ] Persist those settings and have the downloaders read them instead of the
      process-wide `PREFERRED_AUDIO_LANG` default.
- [ ] Keep admin-only commands out of the public menu.

## Support channel (owner decision, 2026-10-21)

- [ ] On a user-facing error, attach an inline button that opens a report.
- [ ] Store tickets with user id, platform, URL, error code, and timestamp.
- [ ] Deliver each new ticket to `ADMIN_ID`/`OWNER_ID` with the context attached.
- [ ] Let the admin reply to a ticket; deliver that reply to the reporting user
      as a message from the bot.
- [ ] Support a status on a ticket (open, cause known, fixed) and notify the
      reporter when it changes.
- [ ] Rate-limit reports per user so the channel cannot be flooded.
- [ ] Keep the admin reply path authorised; never let a user id from a payload
      decide who receives a message.
