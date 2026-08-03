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
from services.chaos.events import replay_chain
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
            validate_run(_payload(v=2), now=NOW)

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
