# TODO

## Bot controls: remaining

Shipped in 1.8.0: the persistent keyboard, the published command menu, and the
quality, audio-language and group-opt-out settings.

- [ ] Default format per user (video vs MP3); the picker already offers both,
      the preference does not exist yet.
- [ ] Prefer a non-`-drc` audio track: YouTube also publishes a loudness
      compressed variant, and ties are currently broken by size, so it can win.

## Support channel

Shipped in 1.9.0: the report button, numbered tickets with context, admin
replies delivered as the bot, statuses that notify the reporter, a per-user
quota, and the reply path addressed from the ticket row rather than the payload.

- [ ] Let the reporter add to an existing ticket instead of opening a new one.
- [ ] Clean up tickets closed long ago, the way `cleanup_stale_state` does for
      callbacks and playlists.

