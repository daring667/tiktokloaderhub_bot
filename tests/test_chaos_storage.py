"""Tests for services/chaos/storage.py — the separate chaos.db."""
import pytest

from services.chaos.storage import ChaosStorage


@pytest.fixture()
def store(tmp_path):
    storage = ChaosStorage(db_path=str(tmp_path / "chaos.db"))
    yield storage
    storage.close()


def _run(day="2026-08-03", apples=8, score=120):
    return {
        "day_key": day, "apples": apples, "score": score,
        "duration_ms": 60000, "events": ["c:speed", "r:portal"],
        "cleared": apples >= 7,
    }


class TestRuns:
    def test_saves_and_counts(self, store):
        store.save_run(1, "Аня", _run())
        store.save_run(1, "Аня", _run(score=200))
        assert store.count_submissions(1, "2026-08-03") == 2

    def test_counts_are_per_day(self, store):
        store.save_run(1, "Аня", _run(day="2026-08-02"))
        assert store.count_submissions(1, "2026-08-03") == 0

    def test_personal_best_is_the_highest_score(self, store):
        store.save_run(1, "Аня", _run(score=120))
        store.save_run(1, "Аня", _run(score=300))
        store.save_run(1, "Аня", _run(score=50))
        assert store.get_personal_best(1, "2026-08-03")["score"] == 300

    def test_no_runs_means_no_personal_best(self, store):
        assert store.get_personal_best(1, "2026-08-03") is None


class TestDailyTop:
    def test_orders_by_score(self, store):
        store.save_run(1, "Аня", _run(score=100))
        store.save_run(2, "Боря", _run(score=300))
        store.save_run(3, "Вера", _run(score=200))

        top = store.get_daily_top("2026-08-03")
        assert [row["display_name"] for row in top] == ["Боря", "Вера", "Аня"]

    def test_one_row_per_player(self, store):
        """Ten attempts must not fill the leaderboard with one name."""
        for score in range(10, 110, 10):
            store.save_run(1, "Аня", _run(score=score))
        store.save_run(2, "Боря", _run(score=55))

        top = store.get_daily_top("2026-08-03")
        assert len(top) == 2
        assert top[0]["display_name"] == "Аня"
        assert top[0]["score"] == 100

    def test_respects_the_limit(self, store):
        for user_id in range(1, 8):
            store.save_run(user_id, f"Игрок{user_id}", _run(score=user_id * 10))
        assert len(store.get_daily_top("2026-08-03", limit=3)) == 3

    def test_ignores_other_days(self, store):
        store.save_run(1, "Аня", _run(day="2026-08-02"))
        assert store.get_daily_top("2026-08-03") == []


class TestStreaks:
    def test_unknown_player_has_no_streak(self, store):
        assert store.get_streak(999) == {"current": 0, "best": 0, "last_day_key": None}

    def test_first_clear_starts_the_streak(self, store):
        assert store.bump_streak(1, "2026-08-03")["current"] == 1

    def test_consecutive_days_extend_it(self, store):
        store.bump_streak(1, "2026-08-01")
        store.bump_streak(1, "2026-08-02")
        state = store.bump_streak(1, "2026-08-03")
        assert state["current"] == 3
        assert state["best"] == 3

    def test_a_gap_resets_it(self, store):
        store.bump_streak(1, "2026-08-01")
        store.bump_streak(1, "2026-08-02")
        state = store.bump_streak(1, "2026-08-05")
        assert state["current"] == 1

    def test_best_survives_a_reset(self, store):
        for day in ("2026-08-01", "2026-08-02", "2026-08-03"):
            store.bump_streak(1, day)
        state = store.bump_streak(1, "2026-08-10")
        assert state["current"] == 1
        assert state["best"] == 3

    def test_clearing_the_same_day_twice_changes_nothing(self, store):
        store.bump_streak(1, "2026-08-03")
        state = store.bump_streak(1, "2026-08-03")
        assert state["current"] == 1

    def test_streaks_are_per_player(self, store):
        store.bump_streak(1, "2026-08-01")
        store.bump_streak(1, "2026-08-02")
        store.bump_streak(2, "2026-08-02")
        assert store.get_streak(1)["current"] == 2
        assert store.get_streak(2)["current"] == 1


class TestMeta:
    def test_missing_key_is_none(self, store):
        assert store.get_meta("last_announced") is None

    def test_round_trips(self, store):
        store.set_meta("last_announced", "2026-08-03")
        assert store.get_meta("last_announced") == "2026-08-03"

    def test_overwrites(self, store):
        store.set_meta("last_announced", "2026-08-03")
        store.set_meta("last_announced", "2026-08-04")
        assert store.get_meta("last_announced") == "2026-08-04"


def test_downloader_database_is_untouched(store, tmp_path):
    """The whole point of a separate file: chaos.db must not contain — or
    need — anything from the downloader's schema."""
    tables = {
        row["name"] for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert tables == {"chaos_runs", "chaos_streaks", "chaos_meta", "sqlite_sequence"}
