"""Storage for the Chaos challenge — deliberately its own SQLite file.

The downloader's database is left completely alone: no new tables, no
migrations, no foreign keys into `users`. If this feature is ever ripped
out, deleting `chaos.db` is the whole cleanup, and a mistake here cannot
corrupt download history. The price is a denormalised copy of the player's
display name, which is cheap.
"""
import json
import os
import sqlite3
import threading

from services.chaos.seed import shift_day_key

CHAOS_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "chaos.db"
)


class ChaosStorage:
    """SQLite wrapper for runs and streaks. Thread-safe the same way
    BotDatabase is: check_same_thread=False plus a lock around writes."""

    def __init__(self, db_path: str = CHAOS_DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS chaos_runs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    display_name TEXT,
                    day_key     TEXT    NOT NULL,
                    apples      INTEGER NOT NULL,
                    score       INTEGER NOT NULL,
                    duration_ms INTEGER,
                    events      TEXT,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_chaos_day
                    ON chaos_runs(day_key, score DESC);

                CREATE TABLE IF NOT EXISTS chaos_streaks (
                    user_id      INTEGER PRIMARY KEY,
                    current      INTEGER NOT NULL DEFAULT 0,
                    best         INTEGER NOT NULL DEFAULT 0,
                    last_day_key TEXT
                );

                CREATE TABLE IF NOT EXISTS chaos_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
            self._conn.commit()

        # These columns arrived with the chain, after rows already existed.
        # SQLite has no "ADD COLUMN IF NOT EXISTS", so just swallow the error
        # when they are already there.
        for statement in (
            "ALTER TABLE chaos_runs ADD COLUMN stages TEXT",
            "ALTER TABLE chaos_runs ADD COLUMN chain_completed INTEGER NOT NULL DEFAULT 0",
        ):
            with self._lock:
                try:
                    self._conn.execute(statement)
                    self._conn.commit()
                except sqlite3.OperationalError:
                    pass

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def save_run(self, user_id: int, display_name: str, run: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO chaos_runs "
                "(user_id, display_name, day_key, apples, score, duration_ms, "
                " events, stages, chain_completed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, display_name, run["day_key"], run["apples"],
                 run["score"], run["duration_ms"], ",".join(run["events"]),
                 json.dumps(run.get("stages", []), ensure_ascii=False),
                 int(bool(run.get("chain_completed")))),
            )
            self._conn.commit()

    def count_submissions(self, user_id: int, day_key_value: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM chaos_runs WHERE user_id = ? AND day_key = ?",
            (user_id, day_key_value),
        ).fetchone()
        return row["n"] if row else 0

    def get_personal_best(self, user_id: int, day_key_value: str):
        return self._conn.execute(
            "SELECT apples, score FROM chaos_runs "
            "WHERE user_id = ? AND day_key = ? ORDER BY score DESC LIMIT 1",
            (user_id, day_key_value),
        ).fetchone()

    def get_daily_top(self, day_key_value: str, limit: int = 10) -> list:
        """Best run per player for the day, strongest first.

        Uses a window function rather than GROUP BY with MAX(). SQLite only
        promises that bare columns come from the max() row when the query has
        exactly one min()/max(); with two — the score and the chain flag —
        the rest of the row is undefined, and the leaderboard would show a
        score from one run beside the apple count from another.

        `chain_completed` is deliberately the whole day, not just the best
        run: finishing the chain is an achievement of the day, and hiding it
        because a later throwaway attempt scored higher would be perverse.
        """
        rows = self._conn.execute(
            "SELECT user_id, display_name, score, apples, duration_ms, chain_completed "
            "FROM ("
            "  SELECT user_id, display_name, score, apples, duration_ms,"
            "         MAX(chain_completed) OVER (PARTITION BY user_id) AS chain_completed,"
            "         ROW_NUMBER() OVER ("
            "           PARTITION BY user_id ORDER BY score DESC, id ASC"
            "         ) AS rn"
            "  FROM chaos_runs WHERE day_key = ?"
            ") WHERE rn = 1 ORDER BY score DESC LIMIT ?",
            (day_key_value, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Streaks
    # ------------------------------------------------------------------

    def get_streak(self, user_id: int) -> dict:
        row = self._conn.execute(
            "SELECT current, best, last_day_key FROM chaos_streaks WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return {"current": 0, "best": 0, "last_day_key": None}
        return dict(row)

    def bump_streak(self, user_id: int, day_key_value: str) -> dict:
        """Records that the player cleared `day_key_value`.

        Clearing the same day twice changes nothing — the streak counts days,
        not runs.
        """
        with self._lock:
            state = self.get_streak(user_id)
            if state["last_day_key"] == day_key_value:
                return state

            consecutive = state["last_day_key"] == shift_day_key(day_key_value, -1)
            current = state["current"] + 1 if consecutive else 1
            best = max(state["best"], current)

            self._conn.execute(
                "INSERT INTO chaos_streaks (user_id, current, best, last_day_key) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "current = excluded.current, best = excluded.best, "
                "last_day_key = excluded.last_day_key",
                (user_id, current, best, day_key_value),
            )
            self._conn.commit()
            return {"current": current, "best": best, "last_day_key": day_key_value}

    # ------------------------------------------------------------------
    # Bookkeeping for the daily announcement
    # ------------------------------------------------------------------

    def get_meta(self, key: str):
        row = self._conn.execute(
            "SELECT value FROM chaos_meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO chaos_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
