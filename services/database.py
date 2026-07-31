"""
SQLite database for user analytics and download tracking.
Thread-safe: uses check_same_thread=False + threading.Lock for writes.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_database.db")


class BotDatabase:
    """Lightweight SQLite wrapper for bot analytics."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self):
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id    INTEGER PRIMARY KEY,
                    username   TEXT,
                    first_name TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS downloads (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL,
                    platform      TEXT    NOT NULL,
                    url           TEXT,
                    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS callbacks (
                    token      TEXT PRIMARY KEY,
                    url        TEXT NOT NULL,
                    itag       TEXT NOT NULL,
                    type       TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS errors (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform    TEXT NOT NULL,
                    error_type  TEXT,
                    message     TEXT,
                    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS playlist_state (
                    token       TEXT PRIMARY KEY,
                    video_urls  TEXT NOT NULL,
                    index_pos   INTEGER NOT NULL DEFAULT 0,
                    total_count INTEGER,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            self._conn.commit()

            # Migrations: these columns didn't exist in earlier versions.
            # SQLite has no "ADD COLUMN IF NOT EXISTS", so just swallow the
            # error if they're already there.
            for migration in (
                "ALTER TABLE users ADD COLUMN broadcast_opt_out INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE callbacks ADD COLUMN playlist_token TEXT",
            ):
                try:
                    cur.execute(migration)
                    self._conn.commit()
                except sqlite3.OperationalError:
                    pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_user(self, user_id: int, username: str | None = None,
                      first_name: str | None = None) -> None:
        """Insert or update user info (upsert)."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username   = COALESCE(excluded.username, users.username),
                    first_name = COALESCE(excluded.first_name, users.first_name)
                """,
                (user_id, username, first_name),
            )
            self._conn.commit()

    def log_download(self, user_id: int, platform: str, url: str = "") -> None:
        """Record a successful download."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO downloads (user_id, platform, url) VALUES (?, ?, ?)",
                (user_id, platform, url),
            )
            self._conn.commit()

    def log_error(self, platform: str, error_type: str = "", message: str = "") -> None:
        """Record a failed download for /stats error-rate reporting."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO errors (platform, error_type, message) VALUES (?, ?, ?)",
                (platform, error_type, message),
            )
            self._conn.commit()

    def get_user_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM users")
        return cur.fetchone()[0]

    def get_broadcast_subscribed_user_ids(self) -> list[int]:
        """Registered user IDs that haven't opted out of broadcasts."""
        rows = self._conn.execute(
            "SELECT user_id FROM users WHERE broadcast_opt_out = 0"
        ).fetchall()
        return [row["user_id"] for row in rows]

    def get_user_display_names(self, user_ids) -> dict:
        """Maps user_id -> a human-readable label (@username, first name,
        or the raw ID as a last resort), for showing broadcast results."""
        user_ids = list(user_ids)
        if not user_ids:
            return {}
        placeholders = ",".join("?" for _ in user_ids)
        rows = self._conn.execute(
            f"SELECT user_id, username, first_name FROM users WHERE user_id IN ({placeholders})",
            user_ids,
        ).fetchall()
        labels = {}
        for row in rows:
            if row["username"]:
                labels[row["user_id"]] = f"@{row['username']}"
            elif row["first_name"]:
                labels[row["user_id"]] = row["first_name"]
            else:
                labels[row["user_id"]] = str(row["user_id"])
        return labels

    def set_broadcast_opt_out(self, user_id: int, opted_out: bool = True) -> None:
        """Mark a user as (not) wanting to receive /broadcast messages."""
        with self._lock:
            self._conn.execute(
                "UPDATE users SET broadcast_opt_out = ? WHERE user_id = ?",
                (1 if opted_out else 0, user_id),
            )
            self._conn.commit()

    def get_download_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM downloads")
        return cur.fetchone()[0]

    def get_stats(self) -> dict:
        """Return aggregate statistics for the /stats command."""
        total_users = self.get_user_count()
        total_downloads = self.get_download_count()

        # Downloads per platform
        rows = self._conn.execute(
            "SELECT platform, COUNT(*) AS cnt FROM downloads GROUP BY platform"
        ).fetchall()
        by_platform = {row["platform"]: row["cnt"] for row in rows}

        # Active users in the last 24 hours
        active_24h = self._conn.execute(
            """
            SELECT COUNT(DISTINCT user_id) FROM downloads
            WHERE downloaded_at >= datetime('now', '-1 day')
            """
        ).fetchone()[0]

        # Bot first-seen date
        first_user = self._conn.execute(
            "SELECT MIN(first_seen) FROM users"
        ).fetchone()[0]

        # Downloads and errors per platform in the last 24 hours (for error rates)
        downloads_24h_rows = self._conn.execute(
            """
            SELECT platform, COUNT(*) AS cnt FROM downloads
            WHERE downloaded_at >= datetime('now', '-1 day')
            GROUP BY platform
            """
        ).fetchall()
        downloads_24h_by_platform = {row["platform"]: row["cnt"] for row in downloads_24h_rows}

        errors_24h_rows = self._conn.execute(
            """
            SELECT platform, COUNT(*) AS cnt FROM errors
            WHERE occurred_at >= datetime('now', '-1 day')
            GROUP BY platform
            """
        ).fetchall()
        errors_24h_by_platform = {row["platform"]: row["cnt"] for row in errors_24h_rows}

        return {
            "total_users": total_users,
            "total_downloads": total_downloads,
            "by_platform": by_platform,
            "active_24h": active_24h,
            "first_seen": first_user,
            "downloads_24h_by_platform": downloads_24h_by_platform,
            "errors_24h_by_platform": errors_24h_by_platform,
        }

    def save_callback(self, token: str, url: str, itag: str, stream_type: str | None = None,
                      playlist_token: str | None = None) -> None:
        """Save a callback token for YouTube quality selection.

        `playlist_token` ties this picker back to a playlist step-through
        session, so the bot knows to offer the next video once the user has
        finally chosen a quality.
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO callbacks (token, url, itag, type, playlist_token) VALUES (?, ?, ?, ?, ?)",
                (token, url, str(itag), stream_type, playlist_token),
            )
            self._conn.commit()

    def get_callback(self, token: str) -> dict | None:
        """Get callback data by token."""
        cur = self._conn.execute(
            "SELECT url, itag, type, playlist_token FROM callbacks WHERE token = ?", (token,)
        )
        row = cur.fetchone()
        if row:
            return dict(row)
        return None

    def delete_callback(self, token: str) -> None:
        """Delete a callback token after use."""
        with self._lock:
            self._conn.execute("DELETE FROM callbacks WHERE token = ?", (token,))
            self._conn.commit()

    def save_playlist_state(self, token: str, video_urls: list, total_count: int) -> None:
        """Starts a step-through session for a YouTube playlist."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO playlist_state (token, video_urls, index_pos, total_count) VALUES (?, ?, 0, ?)",
                (token, json.dumps(video_urls), total_count),
            )
            self._conn.commit()

    def get_playlist_state(self, token: str) -> dict | None:
        """Current position in a playlist step-through session."""
        row = self._conn.execute(
            "SELECT video_urls, index_pos, total_count FROM playlist_state WHERE token = ?",
            (token,),
        ).fetchone()
        if not row:
            return None
        return {
            "video_urls": json.loads(row["video_urls"]),
            "index_pos": row["index_pos"],
            "total_count": row["total_count"],
        }

    def advance_playlist_state(self, token: str) -> dict | None:
        """Moves the session to the next video and returns the new state."""
        with self._lock:
            self._conn.execute(
                "UPDATE playlist_state SET index_pos = index_pos + 1 WHERE token = ?",
                (token,),
            )
            self._conn.commit()
        return self.get_playlist_state(token)

    def delete_playlist_state(self, token: str) -> None:
        """Ends a playlist step-through session."""
        with self._lock:
            self._conn.execute("DELETE FROM playlist_state WHERE token = ?", (token,))
            self._conn.commit()

    def cleanup_stale_state(self, max_age_hours: int = 24) -> dict:
        """Drops abandoned callback tokens and playlist sessions.

        Both are only deleted on the happy path (button pressed / playlist
        finished), so without this they accumulate forever. Returns how many
        rows were removed from each table.
        """
        cutoff = f"-{int(max_age_hours)} hours"
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM callbacks WHERE created_at < datetime('now', ?)", (cutoff,)
            )
            callbacks_removed = cur.rowcount
            cur = self._conn.execute(
                "DELETE FROM playlist_state WHERE created_at < datetime('now', ?)", (cutoff,)
            )
            playlists_removed = cur.rowcount
            self._conn.commit()
        return {"callbacks": callbacks_removed, "playlist_state": playlists_removed}

    def close(self):
        self._conn.close()
