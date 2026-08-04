"""Tests for services/chaos/validate.py.

The client is trusted to compute its own score, so these checks are the only
thing between the leaderboard and a hand-edited payload. They can't stop a
determined cheat — they're here to reject everything easier than replaying
the day's real event chain by hand.
"""
import json
import pytest
from datetime import datetime, timezone

from services.chaos import seed as seed_mod
from services.chaos.events import MERGE_TARGET, merge_mod_for_day, replay_chain
from services.chaos.validate import (
    MAX_SUBMISSIONS_PER_DAY, RunRejected, validate_run,
)

# 12:00 UTC is 17:00 in Almaty, comfortably inside the game day that began
# at noon local time.
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
TODAY = "2026-08-03"


@pytest.fixture(autouse=True)
def _fixed_config(monkeypatch):
    monkeypatch.setattr(seed_mod, "TZ_OFFSET_HOURS", 5)
    monkeypatch.setattr(seed_mod, "DAY_START_HOUR", 12)


def _payload(**overrides):
    apples = overrides.pop("apples", 8)
    payload = {
        "v": 1,
        "day": TODAY,
        "apples": apples,
        "score": 120,
        "ms": 60000,
        "events": replay_chain(TODAY, apples),
    }
    payload.update(overrides)
    return payload


class TestAcceptsHonestRuns:
    def test_accepts_a_plain_run(self):
        result = validate_run(_payload(), now=NOW)
        assert result["apples"] == 8
        assert result["score"] == 120
        assert result["day_key"] == TODAY

    def test_accepts_json_string(self):
        result = validate_run(json.dumps(_payload()), now=NOW)
        assert result["score"] == 120

    def test_marks_the_day_cleared_at_seven_apples(self):
        assert validate_run(_payload(apples=7), now=NOW)["cleared"] is True

    def test_six_apples_do_not_clear_the_day(self):
        assert validate_run(_payload(apples=6), now=NOW)["cleared"] is False

    def test_accepts_a_zero_apple_run(self):
        result = validate_run(_payload(apples=0, score=0, ms=1200), now=NOW)
        assert result["apples"] == 0
        assert result["cleared"] is False


class TestTimingFloor:
    """The floor has to sit at the physically fastest honest run, not at a
    typical one — a run that got lucky with apple placement is still real."""

    def test_accepts_a_lucky_fast_run(self):
        # Four stacked speed modifiers put a tick at 72 ms, and an apple can
        # spawn right in front of the head.
        result = validate_run(_payload(apples=10, score=200, ms=800), now=NOW)
        assert result["apples"] == 10

    def test_rejects_a_physically_impossible_run(self):
        with pytest.raises(RunRejected, match="слишком короткий"):
            validate_run(_payload(apples=10, score=200, ms=100), now=NOW)


class TestRealClientPayloads:
    """Captured from the actual Mini App running in a browser, to catch a
    client/server format drift that unit tests written on one side would
    both agree about and both get wrong."""

    def test_accepts_a_recorded_run(self):
        raw = ('{"v":1,"day":"2026-08-03","apples":2,"score":22,"ms":2432,'
               '"events":["c:walls","c:speed"]}')
        result = validate_run(raw, now=NOW)
        assert result["score"] == 22
        assert result["events"] == ["c:walls", "c:speed"]

    def test_accepts_a_recorded_empty_run(self):
        raw = '{"v":1,"day":"2026-08-03","apples":0,"score":0,"ms":1506,"events":[]}'
        assert validate_run(raw, now=NOW)["apples"] == 0


class TestRejects:
    def test_rejects_malformed_json(self):
        with pytest.raises(RunRejected, match="JSON"):
            validate_run("{not json", now=NOW)

    def test_rejects_unknown_version(self):
        with pytest.raises(RunRejected, match="версия"):
            validate_run(_payload(v=3), now=NOW)

    def test_rejects_another_day(self):
        with pytest.raises(RunRejected, match="другому игровому дню"):
            validate_run(_payload(day="2026-08-02"), now=NOW)

    def test_rejects_inflated_score(self):
        # 5000 is inside the absolute range check, so this exercises the
        # per-apple ceiling rather than the blanket bound: two apples can
        # never be worth more than a few hundred points.
        with pytest.raises(RunRejected, match="очки невозможны"):
            validate_run(_payload(apples=2, score=5000, ms=60000), now=NOW)

    def test_rejects_score_beyond_any_possible_run(self):
        with pytest.raises(RunRejected, match="score"):
            validate_run(_payload(apples=2, score=10 ** 9, ms=60000), now=NOW)

    def test_rejects_impossibly_fast_run(self):
        with pytest.raises(RunRejected, match="слишком короткий"):
            validate_run(_payload(apples=50, score=100, ms=1000), now=NOW)

    def test_rejects_wrong_event_chain(self):
        broken = _payload()
        broken["events"] = ["c:speed"] * len(broken["events"])
        with pytest.raises(RunRejected, match="цепочка событий"):
            validate_run(broken, now=NOW)

    def test_rejects_chain_of_wrong_length(self):
        short = _payload()
        short["events"] = short["events"][:-1]
        with pytest.raises(RunRejected, match="цепочка событий"):
            validate_run(short, now=NOW)

    def test_rejects_once_the_daily_cap_is_reached(self):
        with pytest.raises(RunRejected, match="слишком много отправок"):
            validate_run(_payload(), now=NOW,
                         submissions_today=MAX_SUBMISSIONS_PER_DAY)

    def test_rejects_negative_values(self):
        with pytest.raises(RunRejected, match="apples"):
            validate_run(_payload(apples=-1), now=NOW)

    def test_rejects_non_integer_score(self):
        with pytest.raises(RunRejected, match="score"):
            validate_run(_payload(score="сто"), now=NOW)

    def test_rejects_boolean_dressed_as_number(self):
        # bool is an int subclass in Python; without an explicit guard
        # True would sail through as 1.
        with pytest.raises(RunRejected, match="apples"):
            validate_run(_payload(apples=True), now=NOW)

    def test_rejects_events_that_are_not_strings(self):
        with pytest.raises(RunRejected, match="events"):
            validate_run(_payload(events=[1, 2, 3]), now=NOW)

    def test_rejects_a_bare_list(self):
        with pytest.raises(RunRejected, match="объект"):
            validate_run([1, 2, 3], now=NOW)


def _snake_stage(apples=8, score=100, ms=60000):
    return {"g": "snake", "apples": apples, "score": score, "ms": ms,
            "events": replay_chain(TODAY, apples)}


def _merge_stage(score=400, moves=60, ms=30000, best=128, cleared=None, mod=None):
    return {"g": "merge", "score": score, "moves": moves, "ms": ms, "best": best,
            "cleared": best >= MERGE_TARGET if cleared is None else cleared,
            "mod": mod or merge_mod_for_day(TODAY)}


def _chain(*stages):
    stages = list(stages)
    return {"v": 2, "day": TODAY,
            "score": sum(s["score"] for s in stages),
            "ms": sum(s["ms"] for s in stages),
            "stages": stages}


class TestChain:
    """v2 payloads: one entry per link of the chain."""

    def test_accepts_snake_only(self):
        result = validate_run(_chain(_snake_stage()), now=NOW)
        assert result["apples"] == 8
        assert result["chain_completed"] is False

    def test_accepts_a_completed_chain(self):
        result = validate_run(_chain(_snake_stage(), _merge_stage()), now=NOW)
        assert result["chain_completed"] is True
        assert result["score"] == 500
        assert [s["g"] for s in result["stages"]] == ["snake", "merge"]

    def test_unfinished_merge_still_clears_the_day(self):
        """Reaching the second link means snake was already cleared, so the
        streak must not depend on finishing it."""
        result = validate_run(
            _chain(_snake_stage(apples=9), _merge_stage(best=64)), now=NOW)
        assert result["cleared"] is True
        assert result["chain_completed"] is False

    def test_rejects_a_chain_that_skips_snake(self):
        with pytest.raises(RunRejected, match="начинаться со змейки"):
            validate_run(_chain(_merge_stage()), now=NOW)

    def test_rejects_merge_without_clearing_snake(self):
        with pytest.raises(RunRejected, match="без зачёта"):
            validate_run(_chain(_snake_stage(apples=3, score=40),
                                _merge_stage()), now=NOW)

    def test_rejects_a_total_that_is_not_the_sum(self):
        payload = _chain(_snake_stage(), _merge_stage())
        payload["score"] += 1000
        with pytest.raises(RunRejected, match="сумме звеньев"):
            validate_run(payload, now=NOW)

    def test_rejects_the_wrong_daily_modifier(self):
        wrong = "frozen" if merge_mod_for_day(TODAY) != "frozen" else "rotate"
        with pytest.raises(RunRejected, match="модификатор"):
            validate_run(_chain(_snake_stage(), _merge_stage(mod=wrong)), now=NOW)

    def test_rejects_a_cleared_flag_that_does_not_match_the_tile(self):
        with pytest.raises(RunRejected, match="не сходится"):
            validate_run(
                _chain(_snake_stage(), _merge_stage(best=64, cleared=True)), now=NOW)

    def test_rejects_impossible_merge_score(self):
        with pytest.raises(RunRejected, match="очки невозможны для"):
            validate_run(_chain(_snake_stage(), _merge_stage(score=999999, moves=10)),
                         now=NOW)

    def test_rejects_merge_played_faster_than_a_human_can(self):
        with pytest.raises(RunRejected, match="физически возможно"):
            validate_run(_chain(_snake_stage(), _merge_stage(moves=200, ms=100)),
                         now=NOW)

    def test_rejects_an_unknown_link(self):
        payload = _chain(_snake_stage())
        payload["stages"].append({"g": "tetris", "score": 0})
        payload["score"] = 100
        with pytest.raises(RunRejected, match="неизвестное звено"):
            validate_run(payload, now=NOW)

    def test_rejects_empty_stages(self):
        with pytest.raises(RunRejected, match="непустой список"):
            validate_run({"v": 2, "day": TODAY, "score": 0, "ms": 0, "stages": []},
                         now=NOW)

    def test_v1_still_accepted_after_the_upgrade(self):
        """A Mini App left open across a deploy keeps sending v1."""
        result = validate_run(_payload(), now=NOW)
        assert result["chain_completed"] is False
        assert result["stages"][0]["g"] == "snake"


class TestRealChainPayload:
    def test_accepts_a_payload_captured_from_the_browser(self):
        raw = ('{"v":2,"day":"2026-08-03","score":878,"ms":18007,"stages":['
               '{"g":"snake","apples":9,"score":126,"ms":18000,"events":%s},'
               '{"g":"merge","score":752,"best":64,"moves":100,"ms":7000,'
               '"mod":"rotate","cleared":false}]}')
        import json as _json
        raw = raw % _json.dumps(replay_chain("2026-08-03", 9))
        result = validate_run(raw, now=NOW)
        assert result["score"] == 878
        assert result["chain_completed"] is False
