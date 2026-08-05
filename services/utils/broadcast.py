import asyncio

# Failures that repeat every time until something changes on the user's side.
# The big one is a user who never opened a private chat with the bot — they
# can land in the users table just by dropping a link in a group, and
# Telegram will not let a bot message them at all. Retrying those on every
# broadcast is pure noise. A flood wait or a network blip is deliberately not
# here: those are worth trying again.
PERMANENT_FAILURE_MARKERS = (
    "PEER_ID_INVALID",
    "USER_IS_BLOCKED",
    "USER_IS_DEACTIVATED",
    "USER_DEACTIVATED",
    "INPUT_USER_DEACTIVATED",
    "chat not found",
    "bot was blocked",
)


def is_permanent_failure(error_message) -> bool:
    """Whether this delivery error means "do not bother again"."""
    if not error_message:
        return False
    text = str(error_message)
    return any(marker in text for marker in PERMANENT_FAILURE_MARKERS)


async def broadcast_message(client, user_ids, text: str, delay: float = 0.05, reply_markup=None) -> list[tuple[int, bool, str | None]]:
    """Sends `text` to every ID in `user_ids`, one at a time with a small
    delay to stay well under Telegram's rate limits.

    Returns a list of (user_id, success, error_message) in the same order
    as `user_ids`, so the caller can show exactly who did and didn't get
    it — not just totals. A failure for one user (blocked the bot,
    deactivated account, etc.) never stops the rest of the broadcast.
    """
    results = []
    for user_id in user_ids:
        try:
            await client.send_message(user_id, text, reply_markup=reply_markup)
            results.append((user_id, True, None))
        except Exception as e:
            results.append((user_id, False, str(e)))
        await asyncio.sleep(delay)
    return results
