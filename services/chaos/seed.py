"""Deterministic per-day randomness for the Chaos challenge.

Everyone playing today gets the same sequence of events. Without that,
comparing scores is meaningless and there is nothing for players to talk
about — so the randomness is derived from the date rather than from a live
RNG, and the derivation has to produce identical results in two places:
here (validating what the Mini App sends back) and in the JavaScript client
(actually running the game).
"""
import hashlib
import os
from datetime import datetime, timedelta, timezone

# The game day rolls over at noon Almaty time, not midnight: people play
# over lunch, and a midday boundary avoids a switch that happens while
# everyone is asleep.
TZ_OFFSET_HOURS = int(os.getenv("CHAOS_TZ_OFFSET", "5"))
DAY_START_HOUR = int(os.getenv("CHAOS_DAY_START_HOUR", "12"))
SALT = os.getenv("CHAOS_SALT", "chaos-chain")

MASK32 = 0xFFFFFFFF


def day_key(now: datetime | None = None) -> str:
    """Identifier of the current game day, e.g. "2026-08-03".

    `now` is expected to be timezone-aware; a naive value is read as UTC.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(timezone.utc) + timedelta(hours=TZ_OFFSET_HOURS)
    return (local - timedelta(hours=DAY_START_HOUR)).strftime("%Y-%m-%d")


def shift_day_key(key: str, days: int) -> str:
    """Day key `days` away from `key` — used to tell whether a streak is
    still consecutive."""
    return (datetime.strptime(key, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def seed_for_day(key: str) -> int:
    """Maps a day key to the uint32 seed both sides start from."""
    digest = hashlib.sha256((key + SALT).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def mulberry32(seed: int):
    """Port of the JavaScript mulberry32 PRNG, bit for bit.

    JS does this arithmetic on 32-bit integers (`|0`, `Math.imul`, `>>>`),
    so every step is masked back to 32 bits. Multiplication modulo 2**32 is
    the same whether the operands are read as signed or unsigned, which is
    why working in unsigned throughout still matches `Math.imul`.

    Verified against vectors generated with node — see tests/test_chaos_seed.py.
    """
    a = seed & MASK32

    def rand() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & MASK32
        t = a
        t = ((t ^ (t >> 15)) * (1 | t)) & MASK32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & MASK32)) & MASK32) ^ t
        return ((t ^ (t >> 14)) & MASK32) / 4294967296.0

    return rand


def rng_for_day(key: str):
    """Convenience: the day's PRNG, ready to draw from."""
    return mulberry32(seed_for_day(key))
