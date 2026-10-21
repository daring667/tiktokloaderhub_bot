"""
SQLite database for user analytics and download tracking.
Thread-safe: uses check_same_thread=False + threading.Lock for writes.
"""
import json
import os
import sqlite3
import threading


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

                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id    INTEGER NOT NULL,
                    key        TEXT    NOT NULL,
                    value      TEXT    NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, key)
                );

                CREATE TABLE IF NOT EXISTS support_tickets (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    platform   TEXT,
                    url        TEXT,
                    error_type TEXT,
                    message    TEXT    NOT NULL,
                    status     TEXT    NOT NULL DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS support_replies (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id  INTEGER NOT NULL,
                    author     TEXT    NOT NULL,
                    message    TEXT    NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- The last failure a user hit, so a report filed afterwards
                -- carries the link and the error without them retyping it.
                CREATE TABLE IF NOT EXISTS support_context (
                    user_id    INTEGER PRIMARY KEY,
                    platform   TEXT,
                    url        TEXT,
                    error_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- "The next message from this user is a report / a reply."
                -- In the database rather than in memory: a restart in the
                -- middle of typing would otherwise swallow what they send.
                CREATE TABLE IF NOT EXISTS pending_actions (
                    user_id    INTEGER PRIMARY KEY,
                    action     TEXT    NOT NULL,
                    ticket_id  INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            self._conn.commit()

            # Migrations: these columns didn't exist in earlier versions.
            # SQLite has no "ADD COLUMN IF NOT EXISTS", so just swallow the
            # error if they're already there.
            for migration in (
                "ALTER TABLE users ADD COLUMN broadcast_opt_out INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE users ADD COLUMN broadcast_unreachable INTEGER NOT NULL DEFAULT 0",
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
        """Registered user IDs that haven't opted out and that we have not
        already learned are unreachable.

        A user can reach this table without ever opening a private chat with
        the bot — dropping a link in a group is enough — and Telegram will not
        let a bot message someone who never started it. Those deliveries fail
        identically every time, so once seen they are skipped. Sending /start
        in a private chat clears the mark.
        """
        rows = self._conn.execute(
            "SELECT user_id FROM users "
            "WHERE broadcast_opt_out = 0 AND broadcast_unreachable = 0"
        ).fetchall()
        return [row["user_id"] for row in rows]

    def mark_broadcast_unreachable(self, user_ids) -> int:
        """Flags users whose delivery failed for a reason that will repeat."""
        user_ids = list(user_ids)
        if not user_ids:
            return 0
        placeholders = ",".join("?" * len(user_ids))
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE users SET broadcast_unreachable = 1 "
                f"WHERE user_id IN ({placeholders})",
                user_ids,
            )
            self._conn.commit()
        return cur.rowcount

    def mark_broadcast_reachable(self, user_id: int) -> None:
        """Undoes the flag — called when someone starts the bot in private,
        which is exactly the event that makes them reachable again."""
        with self._lock:
            self._conn.execute(
                "UPDATE users SET broadcast_unreachable = 0 WHERE user_id = ?",
                (user_id,),
            )
            self._conn.commit()

    def count_unreachable(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE broadcast_unreachable = 1"
        ).fetchone()
        return row["n"] if row else 0

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

    # ------------------------------------------------------------------
    # Per-user settings
    # ------------------------------------------------------------------

    def get_user_settings(self, user_id: int) -> dict:
        """Raw stored preferences for one user; missing keys simply absent.

        Values are returned as written. Deciding what an unknown or retired
        value means is `services.user_settings.normalize`'s job, so a row that
        outlived the option it names cannot strand the user.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM user_settings WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def get_settings_for_users(self, user_ids) -> dict:
        """`get_user_settings` for several users at once."""
        ids = list(user_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT user_id, key, value FROM user_settings "
                f"WHERE user_id IN ({placeholders})",
                ids,
            ).fetchall()
        result = {user_id: {} for user_id in ids}
        for row in rows:
            result[row["user_id"]][row["key"]] = row["value"]
        return result

    def set_user_setting(self, user_id: int, key: str, value: str) -> None:
        """Store one preference, replacing any previous value."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO user_settings (user_id, key, value)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value      = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, key, value),
            )
            self._conn.commit()

    def reset_user_settings(self, user_id: int) -> None:
        """Drop every stored preference, returning the user to the defaults."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM user_settings WHERE user_id = ?", (user_id,)
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Support tickets
    # ------------------------------------------------------------------

    def remember_failure(self, user_id: int, platform: str, url: str,
                         error_type: str) -> None:
        """Keep the last failure so a later report can quote it."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO support_context (user_id, platform, url, error_type)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    platform   = excluded.platform,
                    url        = excluded.url,
                    error_type = excluded.error_type,
                    created_at = CURRENT_TIMESTAMP
                """,
                (user_id, platform, url, error_type),
            )
            self._conn.commit()

    def get_failure_context(self, user_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT platform, url, error_type, created_at "
                "FROM support_context WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def create_ticket(self, user_id: int, message: str, platform: str | None = None,
                      url: str | None = None, error_type: str | None = None) -> int:
        """Open a ticket and return its number, which the reporter is shown."""
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO support_tickets
                    (user_id, platform, url, error_type, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, platform, url, error_type, message),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_ticket(self, ticket_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM support_tickets WHERE id = ?", (ticket_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_tickets(self, statuses=None, limit: int = 20) -> list:
        """Most recently updated first; `statuses` narrows to those states."""
        query = "SELECT * FROM support_tickets"
        params = []
        if statuses:
            statuses = list(statuses)
            query += " WHERE status IN (%s)" % ",".join("?" * len(statuses))
            params.extend(statuses)
        query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def count_open_tickets(self, user_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM support_tickets "
                "WHERE user_id = ? AND status IN ('open', 'investigating')",
                (user_id,),
            ).fetchone()
        return row["n"] if row else 0

    def get_latest_open_ticket(self, user_id: int) -> dict | None:
        """The ticket a new report would most likely be about."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM support_tickets WHERE user_id = ? "
                "AND status IN ('open', 'investigating') "
                "ORDER BY updated_at DESC, id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def set_ticket_status(self, ticket_id: int, status: str) -> bool:
        """True when a ticket was actually updated."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE support_tickets SET status = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, ticket_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def add_reply(self, ticket_id: int, author: str, message: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO support_replies (ticket_id, author, message) "
                "VALUES (?, ?, ?)",
                (ticket_id, author, message),
            )
            self._conn.execute(
                "UPDATE support_tickets SET updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (ticket_id,),
            )
            self._conn.commit()

    def get_replies(self, ticket_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT author, message, created_at FROM support_replies "
                "WHERE ticket_id = ? ORDER BY id",
                (ticket_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # "The next message from this user means something"
    # ------------------------------------------------------------------

    def set_pending(self, user_id: int, action: str,
                    ticket_id: int | None = None) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO pending_actions (user_id, action, ticket_id)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    action     = excluded.action,
                    ticket_id  = excluded.ticket_id,
                    created_at = CURRENT_TIMESTAMP
                """,
                (user_id, action, ticket_id),
            )
            self._conn.commit()

    def get_pending(self, user_id: int, max_age_minutes: int | None = None) -> dict | None:
        """The pending action, if there is one and it has not gone stale.

        An expired row is deleted on the way out. Without this, tapping the
        report button and walking away would leave the prompt armed forever,
        and the next link that person sent would be captured as a bug report
        instead of being downloaded.
        """
        query = ("SELECT action, ticket_id, created_at FROM pending_actions "
                 "WHERE user_id = ?")
        params = [user_id]
        if max_age_minutes is not None:
            query += " AND created_at >= datetime('now', ?)"
            params.append("-%d minutes" % int(max_age_minutes))
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
            if row is None and max_age_minutes is not None:
                self._conn.execute(
                    "DELETE FROM pending_actions WHERE user_id = ?", (user_id,))
                self._conn.commit()
        return dict(row) if row else None

    def clear_pending(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM pending_actions WHERE user_id = ?", (user_id,))
            self._conn.commit()

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
            cur = self._conn.execute(
                "DELETE FROM pending_actions WHERE created_at < datetime('now', ?)",
                (cutoff,)
            )
            pending_removed = cur.rowcount
            cur = self._conn.execute(
                "DELETE FROM support_context WHERE created_at < datetime('now', ?)",
                (cutoff,)
            )
            context_removed = cur.rowcount
            self._conn.commit()
        return {
            "callbacks": callbacks_removed,
            "playlist_state": playlists_removed,
            "pending_actions": pending_removed,
            "support_context": context_removed,
        }

    def cleanup_old_tickets(self, max_age_days: int = 30) -> int:
        """Drops finished tickets, and their replies, after a grace period.

        Only `fixed` and `closed` ones: an open ticket is someone still
        waiting for an answer, however old it is. Replies go first, because
        SQLite will not cascade them on its own.
        """
        cutoff = "-%d days" % int(max_age_days)
        with self._lock:
            self._conn.execute(
                """
                DELETE FROM support_replies WHERE ticket_id IN (
                    SELECT id FROM support_tickets
                    WHERE status IN ('fixed', 'closed')
                      AND updated_at < datetime('now', ?)
                )
                """,
                (cutoff,),
            )
            cur = self._conn.execute(
                "DELETE FROM support_tickets WHERE status IN ('fixed', 'closed') "
                "AND updated_at < datetime('now', ?)",
                (cutoff,),
            )
            removed = cur.rowcount
            # Replies whose ticket is already gone, from any earlier sweep.
            self._conn.execute(
                "DELETE FROM support_replies WHERE ticket_id NOT IN "
                "(SELECT id FROM support_tickets)"
            )
            self._conn.commit()
        return removed

    def close(self):
        self._conn.close()
