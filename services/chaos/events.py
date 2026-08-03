"""The event catalogue, the rarity ladder, and the scoring rules.

This module is the single source of truth for what happens after an apple.
The JavaScript client mirrors it; `tests/test_chaos_events.py` pins the
numbers so the two can't drift silently.
"""
from services.chaos.seed import mulberry32, seed_for_day

COMMON = "common"
RARE = "rare"
EPIC = "epic"
LEGENDARY = "legendary"

RARITY_ORDER = (COMMON, RARE, EPIC, LEGENDARY)

# Short prefixes so a submitted event chain is readable in the database
# and in logs: "c:speed", "e:dark".
RARITY_PREFIX = {COMMON: "c", RARE: "r", EPIC: "e", LEGENDARY: "l"}

PERMANENT = "permanent"   # stays for the rest of the run
TIMED = "timed"           # wears off after `duration` seconds
INSTANT = "instant"       # applies once, nothing to track

# The apple count does not pick the event — it shifts the odds toward rarer
# ones. That way escalation and the rarity table are one mechanic instead of
# two, tension climbs on its own, and a rare event reads as a reward for
# surviving rather than a gift handed out on the first apple.
# Each entry: (applies while apples_eaten <= N, weights). None = "and beyond".
RARITY_LADDER = (
    (2, {COMMON: 90, RARE: 10, EPIC: 0, LEGENDARY: 0}),
    (4, {COMMON: 65, RARE: 28, EPIC: 7, LEGENDARY: 0}),
    (6, {COMMON: 45, RARE: 35, EPIC: 18, LEGENDARY: 2}),
    (None, {COMMON: 25, RARE: 40, EPIC: 30, LEGENDARY: 5}),
)

# Permanent modifiers stack — that is the whole point, by the eighth apple
# you are playing fast, inverted and in the dark at once. But without a cap
# the run stops being a game, so the oldest one falls off when a fifth
# arrives. Timed modifiers don't count against the cap.
MAX_PERMANENT_MODIFIERS = 4

EVENTS = (
    # --- 🟢 common -----------------------------------------------------
    {"id": "speed",    "rarity": COMMON, "kind": PERMANENT, "title": "Разгон",
     "text": "Скорость +20%"},
    {"id": "walls",    "rarity": COMMON, "kind": PERMANENT, "title": "Стены",
     "text": "На поле появились три блока"},
    {"id": "invert",   "rarity": COMMON, "kind": TIMED, "duration": 10,
     "title": "Инверсия", "text": "Управление наоборот, 10 секунд"},
    {"id": "ghost",    "rarity": COMMON, "kind": PERMANENT, "title": "Призрак",
     "text": "Яблоко мигает"},
    {"id": "growth",   "rarity": COMMON, "kind": INSTANT, "title": "Отъедание",
     "text": "+2 сегмента к длине"},

    # --- 🔵 rare -------------------------------------------------------
    {"id": "portal",   "rarity": RARE, "kind": PERMANENT, "title": "Портал",
     "text": "Края поля переключились"},
    {"id": "double",   "rarity": RARE, "kind": TIMED, "duration": 15,
     "multiplier": 2.0, "title": "Двойные очки", "text": "×2 к очкам, 15 секунд"},
    {"id": "mirror",   "rarity": RARE, "kind": PERMANENT, "title": "Зеркало",
     "text": "Поле отразилось по горизонтали"},

    # --- 🟣 epic -------------------------------------------------------
    {"id": "dark",     "rarity": EPIC, "kind": PERMANENT, "title": "Темнота",
     "text": "Видно только вокруг головы"},
    {"id": "golden",   "rarity": EPIC, "kind": INSTANT, "multiplier": 5.0,
     "title": "Золотое яблоко", "text": "Следующее яблоко даёт ×5"},
    {"id": "twins",    "rarity": EPIC, "kind": PERMANENT, "title": "Двойня",
     "text": "На поле два яблока"},

    # --- 🟡 legendary --------------------------------------------------
    {"id": "reverse",  "rarity": LEGENDARY, "kind": TIMED, "duration": 20,
     "title": "Обратный ход", "text": "Хвост стал головой, 20 секунд"},
)

EVENTS_BY_ID = {e["id"]: e for e in EVENTS}
EVENTS_BY_RARITY = {
    rarity: tuple(e for e in EVENTS if e["rarity"] == rarity)
    for rarity in RARITY_ORDER
}

BASE_POINTS_PER_APPLE = 10
# Every active permanent modifier makes each apple worth more. Without this
# the winning strategy is to avoid chaos, which would defeat the idea.
CHAOS_BONUS_PER_MODIFIER = 0.15

# The day counts as cleared at seven apples — the point where a boss will
# eventually appear.
APPLES_TO_CLEAR_DAY = 7


def weights_for(apples_eaten: int) -> dict:
    """Rarity weights that apply to the apple being eaten right now."""
    for threshold, weights in RARITY_LADDER:
        if threshold is None or apples_eaten <= threshold:
            return weights
    return RARITY_LADDER[-1][1]


def pick_rarity(roll: float, apples_eaten: int) -> str:
    """Maps a [0, 1) draw onto a rarity, given how far the run has got."""
    weights = weights_for(apples_eaten)
    total = sum(weights.values())
    target = roll * total
    cumulative = 0
    for rarity in RARITY_ORDER:
        cumulative += weights[rarity]
        if target < cumulative:
            return rarity
    return COMMON  # unreachable while the weights sum above zero


def roll_event(rand, apples_eaten: int) -> dict:
    """Draws one event. Consumes exactly two numbers from `rand`, which is
    what keeps Python and JavaScript in step."""
    rarity = pick_rarity(rand(), apples_eaten)
    pool = EVENTS_BY_RARITY[rarity]
    return pool[int(rand() * len(pool)) % len(pool)]


def event_code(event: dict) -> str:
    return f"{RARITY_PREFIX[event['rarity']]}:{event['id']}"


def replay_chain(day_key_value: str, apples: int) -> list:
    """Rebuilds the exact event chain today's seed produces for `apples`
    apples. Used to check that a submitted run really played today's game."""
    rand = mulberry32(seed_for_day(day_key_value))
    return [event_code(roll_event(rand, i + 1)) for i in range(apples)]


def max_plausible_score(apples: int) -> int:
    """Upper bound on an honest score for this many apples.

    Deliberately generous — it exists to reject "a million points off three
    apples", not to police the last percent.
    """
    best_chaos = 1 + CHAOS_BONUS_PER_MODIFIER * MAX_PERMANENT_MODIFIERS
    best_temp = 2.0 * 5.0  # double points and a golden apple at once
    return int(apples * BASE_POINTS_PER_APPLE * best_chaos * best_temp) + 1
