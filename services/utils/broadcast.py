import asyncio


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
