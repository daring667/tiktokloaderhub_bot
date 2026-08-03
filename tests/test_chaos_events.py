"""Tests for services/chaos/events.py — the rarity ladder and scoring."""
import pytest

from services.chaos.events import (
    COMMON, RARE, EPIC, LEGENDARY, RARITY_ORDER,
    EVENTS, EVENTS_BY_ID, EVENTS_BY_RARITY, MAX_PERMANENT_MODIFIERS,
    event_code, max_plausible_score, pick_rarity, replay_chain,
    roll_event, weights_for,
)
from services.chaos.seed import mulberry32


class TestCatalogue:
    def test_ids_are_unique(self):
        ids = [e["id"] for e in EVENTS]
        assert len(ids) == len(set(ids))

    def test_every_rarity_has_at_least_one_event(self):
        # pick_rarity can return any rarity with a non-zero weight; an empty
        # pool would blow up mid-run.
        for rarity in RARITY_ORDER:
            assert EVENTS_BY_RARITY[rarity], f"нет событий редкости {rarity}"

    def test_timed_events_declare_a_duration(self):
        for event in EVENTS:
            if event["kind"] == "timed":
                assert event.get("duration"), f"{event['id']} без duration"

    def test_event_code_encodes_rarity_and_id(self):
        assert event_code(EVENTS_BY_ID["dark"]) == "e:dark"
        assert event_code(EVENTS_BY_ID["speed"]) == "c:speed"


class TestRarityLadder:
    @pytest.mark.parametrize("apples,expected_common", [
        (1, 90), (2, 90), (3, 65), (4, 65), (5, 45), (6, 45), (7, 25), (50, 25),
    ])
    def test_weights_by_apple_count(self, apples, expected_common):
        assert weights_for(apples)[COMMON] == expected_common

    def test_weights_each_sum_to_100(self):
        for apples in (1, 3, 5, 7):
            assert sum(weights_for(apples).values()) == 100

    def test_escalation_is_monotonic(self):
        """Common gets rarer and legendary gets likelier as the run goes on —
        this is the whole escalation mechanic, so pin it."""
        commons = [weights_for(a)[COMMON] for a in (1, 3, 5, 7)]
        legendaries = [weights_for(a)[LEGENDARY] for a in (1, 3, 5, 7)]
        assert commons == sorted(commons, reverse=True)
        assert legendaries == sorted(legendaries)

    def test_no_legendary_before_the_fifth_apple(self):
        assert weights_for(1)[LEGENDARY] == 0
        assert weights_for(4)[LEGENDARY] == 0
        assert weights_for(5)[LEGENDARY] > 0

    @pytest.mark.parametrize("roll,expected", [
        (0.0, COMMON), (0.24, COMMON),
        (0.25, RARE), (0.64, RARE),
        (0.65, EPIC), (0.94, EPIC),
        (0.95, LEGENDARY), (0.999, LEGENDARY),
    ])
    def test_pick_rarity_boundaries_at_seven_apples(self, roll, expected):
        assert pick_rarity(roll, 7) == expected

    def test_distribution_matches_the_declared_weights(self):
        """10 000 draws should land within a point or so of the table."""
        rand = mulberry32(20260803)
        counts = {r: 0 for r in RARITY_ORDER}
        rounds = 10000
        for _ in range(rounds):
            counts[pick_rarity(rand(), 7)] += 1

        expected = weights_for(7)
        for rarity in RARITY_ORDER:
            share = counts[rarity] / rounds * 100
            assert abs(share - expected[rarity]) < 2, (
                f"{rarity}: получили {share:.1f}%, ожидали {expected[rarity]}%"
            )


class TestRollAndReplay:
    def test_roll_consumes_exactly_two_numbers(self):
        """The JS client relies on this: if the two sides draw a different
        number of values per apple, every later event diverges."""
        drawn = []
        rand = mulberry32(1)

        def counting():
            value = rand()
            drawn.append(value)
            return value

        roll_event(counting, 1)
        assert len(drawn) == 2

    def test_replay_is_deterministic(self):
        assert replay_chain("2026-08-03", 12) == replay_chain("2026-08-03", 12)

    def test_replay_differs_between_days(self):
        assert replay_chain("2026-08-03", 12) != replay_chain("2026-08-04", 12)

    def test_replay_is_a_prefix_as_apples_grow(self):
        """A run that got 5 apples must produce the first 5 events of a run
        that got 10 — otherwise validating a short run would fail."""
        long_chain = replay_chain("2026-08-03", 10)
        assert replay_chain("2026-08-03", 5) == long_chain[:5]

    def test_replay_returns_known_events(self):
        for code in replay_chain("2026-08-03", 30):
            prefix, _, event_id = code.partition(":")
            assert event_id in EVENTS_BY_ID
            assert event_code(EVENTS_BY_ID[event_id]) == code

    def test_empty_run_has_no_events(self):
        assert replay_chain("2026-08-03", 0) == []


class TestScoreBound:
    def test_grows_with_apples(self):
        assert max_plausible_score(10) > max_plausible_score(5)

    def test_allows_a_fully_stacked_run(self):
        """The honest ceiling: every permanent modifier active, plus double
        points and a golden apple at once."""
        honest = 10 * (1 + 0.15 * MAX_PERMANENT_MODIFIERS) * 2.0 * 5.0
        assert max_plausible_score(1) >= honest

    def test_rejects_absurd_scores(self):
        assert max_plausible_score(3) < 9999
