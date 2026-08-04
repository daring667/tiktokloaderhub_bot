"""Sanity checks on a run submitted by the Mini App.

The client computes its own score, so anyone determined enough can lie about
it — there is no server between the game and the bot to prevent that. For an
audience of a dozen friends that trade-off buys us zero hosting cost, and
these checks still reject everything short of deliberately replaying the
day's real event chain by hand.

Two payload versions are accepted. v1 is a bare snake run; v2 carries the
chain, one entry per link. v1 is still honoured because a Mini App left open
across a deploy will keep sending it.
"""
import json

from services.chaos.events import (
    APPLES_TO_CLEAR_DAY,
    MERGE_TARGET,
    max_plausible_score,
    merge_mod_for_day,
    replay_chain,
)
from services.chaos.seed import day_key

SUPPORTED_VERSIONS = (1, 2)

# A snake cannot cross the board and eat an apple faster than one tick. The
# client ticks every 150 ms and four stacked speed modifiers cut that to
# 150 / 1.2**4 = 72 ms, and an apple can spawn directly in front of the head,
# so anything near the average (~1200 ms observed) would reject real runs.
MIN_MS_PER_APPLE = 60

# "Слияние" is turn-based; this is reaction time, not travel time.
MIN_MS_PER_MERGE_MOVE = 40
# Sanity net rather than anti-cheat: the merge board is driven by the
# player's own moves, so there is no chain to replay against.
MAX_MERGE_SCORE_PER_MOVE = 512

MAX_APPLES = 400
MAX_MERGE_MOVES = 5000
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


def _check_snake(stage: dict, today: str) -> dict:
    apples = _require_int(stage, "apples", 0, MAX_APPLES)
    score = _require_int(stage, "score", 0, max_plausible_score(MAX_APPLES))
    duration_ms = _require_int(stage, "ms", 0, 24 * 60 * 60 * 1000)

    if score > max_plausible_score(apples):
        raise RunRejected(f"очки невозможны для {apples} яблок: {score}")
    if duration_ms < apples * MIN_MS_PER_APPLE:
        raise RunRejected("забег слишком короткий для такого числа яблок")

    events = stage.get("events")
    if not isinstance(events, list) or not all(isinstance(e, str) for e in events):
        raise RunRejected("поле events: ожидался список строк")
    if events != replay_chain(today, apples):
        raise RunRejected("цепочка событий не совпадает с сегодняшним сидом")

    return {"apples": apples, "score": score, "ms": duration_ms, "events": events}


def _check_merge(stage: dict, today: str) -> dict:
    moves = _require_int(stage, "moves", 0, MAX_MERGE_MOVES)
    score = _require_int(stage, "score", 0, MAX_MERGE_MOVES * MAX_MERGE_SCORE_PER_MOVE)
    duration_ms = _require_int(stage, "ms", 0, 24 * 60 * 60 * 1000)
    best = _require_int(stage, "best", 0, 1 << 20)

    if score > moves * MAX_MERGE_SCORE_PER_MOVE + MAX_MERGE_SCORE_PER_MOVE:
        raise RunRejected(f"очки невозможны для {moves} ходов: {score}")
    if duration_ms < moves * MIN_MS_PER_MERGE_MOVE:
        raise RunRejected("слияние сыграно быстрее, чем физически возможно")

    expected_mod = merge_mod_for_day(today)
    if stage.get("mod") != expected_mod:
        raise RunRejected("модификатор слияния не тот, что выпал сегодня")

    cleared = stage.get("cleared")
    if not isinstance(cleared, bool):
        raise RunRejected("поле cleared: ожидался булев флаг")
    if cleared != (best >= MERGE_TARGET):
        raise RunRejected("отметка о прохождении не сходится с набранной плиткой")

    return {"score": score, "ms": duration_ms, "moves": moves,
            "best": best, "cleared": cleared}


def _parse(raw) -> dict:
    if isinstance(raw, (str, bytes)):
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise RunRejected(f"не разобрать JSON: {exc}") from exc
    else:
        payload = raw

    if not isinstance(payload, dict):
        raise RunRejected("ожидался объект")
    if payload.get("v") not in SUPPORTED_VERSIONS:
        raise RunRejected(f"неизвестная версия формата: {payload.get('v')!r}")
    return payload


def validate_run(raw, *, now=None, submissions_today: int = 0) -> dict:
    """Parses and checks what the Mini App sent.

    Returns the normalised run on success; raises `RunRejected` otherwise.
    """
    if submissions_today >= MAX_SUBMISSIONS_PER_DAY:
        raise RunRejected("слишком много отправок за сегодня")

    payload = _parse(raw)
    today = day_key(now)
    if payload.get("day") != today:
        # Not necessarily cheating: a tab left open across the noon rollover
        # lands here too, so the wording stays neutral.
        raise RunRejected("результат относится к другому игровому дню")

    if payload["v"] == 1:
        snake = _check_snake(payload, today)
        return {
            "day_key": today,
            "apples": snake["apples"],
            "score": snake["score"],
            "duration_ms": snake["ms"],
            "events": snake["events"],
            "cleared": snake["apples"] >= APPLES_TO_CLEAR_DAY,
            "chain_completed": False,
            "stages": [{"g": "snake", **snake}],
        }

    stages = payload.get("stages")
    if not isinstance(stages, list) or not stages:
        raise RunRejected("поле stages: ожидался непустой список")
    if not all(isinstance(s, dict) for s in stages):
        raise RunRejected("поле stages: ожидались объекты")
    if stages[0].get("g") != "snake":
        raise RunRejected("цепочка обязана начинаться со змейки")

    checked = []
    chain_completed = False
    for stage in stages:
        kind = stage.get("g")
        if kind == "snake":
            checked.append({"g": "snake", **_check_snake(stage, today)})
        elif kind == "merge":
            merge = _check_merge(stage, today)
            chain_completed = merge["cleared"]
            checked.append({"g": "merge", **merge})
        else:
            raise RunRejected(f"неизвестное звено цепочки: {kind!r}")

    snake = checked[0]
    if snake["apples"] < APPLES_TO_CLEAR_DAY and len(checked) > 1:
        raise RunRejected("следующее звено недоступно без зачёта по змейке")

    total_score = _require_int(payload, "score", 0, 10 ** 9)
    if total_score != sum(s["score"] for s in checked):
        raise RunRejected("итоговый счёт не равен сумме звеньев")

    total_ms = _require_int(payload, "ms", 0, 24 * 60 * 60 * 1000)

    return {
        "day_key": today,
        "apples": snake["apples"],
        "score": total_score,
        "duration_ms": total_ms,
        "events": snake["events"],
        "cleared": snake["apples"] >= APPLES_TO_CLEAR_DAY,
        "chain_completed": chain_completed,
        "stages": checked,
    }
