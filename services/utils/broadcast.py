import asyncio


async def broadcast_message(client, user_ids, text: str, delay: float = 0.05, reply_markup=None) -> tuple[int, int]:
    """Sends `text` to every ID in `user_ids`, one at a time with a small
    delay to stay well under Telegram's rate limits.

    Returns (sent, failed). A failure for one user (blocked the bot,
    deactivated account, etc.) never stops the rest of the broadcast.
    """
    sent = 0
    failed = 0
    for user_id in user_ids:
        try:
            await client.send_message(user_id, text, reply_markup=reply_markup)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(delay)
    return sent, failed
