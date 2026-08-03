"""Sanity checks on a run submitted by the Mini App.

The client computes the score, so anyone determined enough can lie about it
— there is no server between the game and the bot to prevent that. For an
audience of a dozen friends that trade-off buys us zero hosting cost, and
these checks still reject everything short of deliberately replaying the
day's real event chain by hand.
"""
import json

from services.chaos.events import (
    APPLES_TO_CLEAR_DAY,
    max_plausible_score,
    replay_chain,
)
from services.chaos.seed import day_key

PAYLOAD_VERSION = 1

# The physical floor for one apple, derived from the client: the snake moves
# one cell per tick at BASE_TICK_MS = 150 ms, and four stacked "speed"
# modifiers cut that to 150 / 1.2**4 = 72 ms. An apple can spawn directly in
# front of the head, so one tick is genuinely the fastest an honest apple can
# be eaten. Anything nearer the average (~1200 ms observed) would reject real
# runs that simply got lucky with apple placement.
MIN_MS_PER_APPLE = 60
MAX_APPLES = 400
MAX_SUBMISSIONS_PER_DAY = 20


class RunRejected(Exception):
    """A submitted run failed validation and must not be recorded."""


def _require_int(payload: dict, field: str, low: int, high: int) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunRejected(f"поле {field}: ожидалось целое число")
    if not low <= value <= high:
        raise RunRejected(f"поле {field}: {value} вне допустимого диапазона")
    return value


def validate_run(raw, *, now=None, submissions_today: int = 0) -> dict:
    """Parses and checks what the Mini App sent.

    Returns the normalised run on success; raises `RunRejected` otherwise.
    """
    if submissions_today >= MAX_SUBMISSIONS_PER_DAY:
        raise RunRejected("слишком много отправок за сегодня")

    if isinstance(raw, (str, bytes)):
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise RunRejected(f"не разобрать JSON: {exc}") from exc
    else:
        payload = raw

    if not isinstance(payload, dict):
        raise RunRejected("ожидался объект")

    if payload.get("v") != PAYLOAD_VERSION:
        raise RunRejected(f"неизвестная версия формата: {payload.get('v')!r}")

    today = day_key(now)
    if payload.get("day") != today:
        # Not necessarily cheating: a tab left open across the noon rollover
        # lands here too, so the wording stays neutral.
        raise RunRejected("результат относится к другому игровому дню")

    apples = _require_int(payload, "apples", 0, MAX_APPLES)
    score = _require_int(payload, "score", 0, max_plausible_score(MAX_APPLES))
    duration_ms = _require_int(payload, "ms", 0, 24 * 60 * 60 * 1000)

    if score > max_plausible_score(apples):
        raise RunRejected(f"очки невозможны для {apples} яблок: {score}")

    if duration_ms < apples * MIN_MS_PER_APPLE:
        raise RunRejected("забег слишком короткий для такого числа яблок")

    events = payload.get("events")
    if not isinstance(events, list) or not all(isinstance(e, str) for e in events):
        raise RunRejected("поле events: ожидался список строк")

    expected = replay_chain(today, apples)
    if events != expected:
        raise RunRejected("цепочка событий не совпадает с сегодняшним сидом")

    return {
        "day_key": today,
        "apples": apples,
        "score": score,
        "duration_ms": duration_ms,
        "events": events,
        "cleared": apples >= APPLES_TO_CLEAR_DAY,
    }
