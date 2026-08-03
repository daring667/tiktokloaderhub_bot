"""Tests for services/chaos/seed.py — the day boundary and the PRNG.

The PRNG matters more than it looks: the Mini App runs the JavaScript copy
to generate events, and the bot runs this one to check that a submitted run
really played today's game. If they ever disagree, every honest result gets
rejected. Hence the reference vectors below.
"""
import pytest
from datetime import datetime, timezone

from services.chaos import seed as seed_mod
from services.chaos.seed import day_key, mulberry32, seed_for_day, shift_day_key

# Generated with the node 20 binary bundled with the GitHub Actions runner:
#   node -e 'function mulberry32(a){...}; ...'
# Values are the raw uint32 the JS version produces before dividing by 2**32,
# so the comparison is exact rather than float-fuzzy.
JS_REFERENCE = {
    0: [1144304738, 1416247, 958946056, 627933444, 2007157716, 2340967985],
    1: [2693262067, 11749833, 2265367787, 4213581821, 4159151403, 1207330352],
    42: [2581720956, 1925393290, 3661312704, 2876485805, 750819978, 2261697747],
    2166136261: [2625274932, 2119670693, 3324411561, 1770755366, 3488654967, 245707362],
    4294967295: [3850105811, 813802916, 3073704848, 4054706436, 3630262831, 2315588663],
}


class TestMulberry32:
    @pytest.mark.parametrize("seed,expected", JS_REFERENCE.items())
    def test_matches_javascript(self, seed, expected):
        rand = mulberry32(seed)
        # value * 2**32 is exact: the generator divides an integer by 2**32,
        # and every such quotient is representable as a double.
        produced = [int(rand() * 4294967296) for _ in expected]
        assert produced == expected

    def test_output_is_in_unit_interval(self):
        rand = mulberry32(12345)
        for _ in range(1000):
            value = rand()
            assert 0.0 <= value < 1.0

    def test_same_seed_gives_same_sequence(self):
        assert [mulberry32(7)() for _ in range(3)] == [mulberry32(7)() for _ in range(3)]


class TestDayKey:
    """The game day starts at noon Almaty (UTC+5), i.e. 07:00 UTC."""

    @pytest.fixture(autouse=True)
    def _fixed_config(self, monkeypatch):
        # Pin the constants rather than trusting ambient env vars, so the
        # test means the same thing on the server and in CI.
        monkeypatch.setattr(seed_mod, "TZ_OFFSET_HOURS", 5)
        monkeypatch.setattr(seed_mod, "DAY_START_HOUR", 12)

    @pytest.mark.parametrize("moment,expected", [
        ("2026-08-03T06:59:59Z", "2026-08-02"),  # one second before noon Almaty
        ("2026-08-03T07:00:00Z", "2026-08-03"),  # exactly noon Almaty
        ("2026-08-03T23:59:59Z", "2026-08-03"),
        ("2026-08-04T06:59:59Z", "2026-08-03"),
        ("2026-08-04T07:00:00Z", "2026-08-04"),
    ])
    def test_rolls_over_at_07_utc(self, moment, expected):
        now = datetime.fromisoformat(moment.replace("Z", "+00:00"))
        assert day_key(now) == expected

    def test_naive_datetime_is_read_as_utc(self):
        naive = datetime(2026, 8, 3, 7, 0, 0)
        aware = datetime(2026, 8, 3, 7, 0, 0, tzinfo=timezone.utc)
        assert day_key(naive) == day_key(aware)

    def test_midnight_is_not_the_boundary(self):
        """Regression guard: a plain UTC date would flip here, this must not."""
        before = datetime(2026, 8, 3, 23, 0, tzinfo=timezone.utc)
        after = datetime(2026, 8, 4, 1, 0, tzinfo=timezone.utc)
        assert day_key(before) == day_key(after) == "2026-08-03"


class TestSeedForDay:
    def test_is_uint32(self):
        value = seed_for_day("2026-08-03")
        assert 0 <= value <= 0xFFFFFFFF

    def test_is_stable(self):
        assert seed_for_day("2026-08-03") == seed_for_day("2026-08-03")

    def test_differs_between_days(self):
        assert seed_for_day("2026-08-03") != seed_for_day("2026-08-04")


class TestShiftDayKey:
    def test_previous_day(self):
        assert shift_day_key("2026-08-03", -1) == "2026-08-02"

    def test_crosses_month(self):
        assert shift_day_key("2026-08-01", -1) == "2026-07-31"

    def test_crosses_year(self):
        assert shift_day_key("2027-01-01", -1) == "2026-12-31"
