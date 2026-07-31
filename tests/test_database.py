"""
Tests for BotDatabase (SQLite analytics).
"""
import sqlite3
import pytest
from services.database import BotDatabase


class TestBotDatabase:
    def test_register_new_user(self, tmp_db):
        tmp_db.register_user(12345, "testuser", "Test")
        assert tmp_db.get_user_count() == 1

    def test_register_duplicate_user_no_duplication(self, tmp_db):
        tmp_db.register_user(12345, "user1", "Name1")
        tmp_db.register_user(12345, "user1", "Name1")
        assert tmp_db.get_user_count() == 1

    def test_upsert_updates_username(self, tmp_db):
        tmp_db.register_user(12345, "old_name", "Test")
        tmp_db.register_user(12345, "new_name", "Test")
        assert tmp_db.get_user_count() == 1

        row = tmp_db._conn.execute(
            "SELECT username FROM users WHERE user_id = 12345"
        ).fetchone()
        assert row["username"] == "new_name"

    def test_upsert_preserves_existing_when_null(self, tmp_db):
        """If new username is None, existing username is preserved."""
        tmp_db.register_user(12345, "original", "Test")
        tmp_db.register_user(12345, None, "Test")

        row = tmp_db._conn.execute(
            "SELECT username FROM users WHERE user_id = 12345"
        ).fetchone()
        assert row["username"] == "original"

    def test_log_download(self, tmp_db):
        tmp_db.register_user(1, "user", "U")
        tmp_db.log_download(1, "tiktok", "https://tiktok.com/video/1")
        assert tmp_db.get_download_count() == 1

    def test_multiple_downloads(self, tmp_db):
        tmp_db.register_user(1, "user", "U")
        tmp_db.log_download(1, "tiktok", "url1")
        tmp_db.log_download(1, "youtube", "url2")
        tmp_db.log_download(1, "tiktok", "url3")
        assert tmp_db.get_download_count() == 3

    def test_get_stats_empty_db(self, tmp_db):
        stats = tmp_db.get_stats()
        assert stats["total_users"] == 0
        assert stats["total_downloads"] == 0
        assert stats["by_platform"] == {}
        assert stats["active_24h"] == 0
        assert stats["first_seen"] is None
        assert stats["downloads_24h_by_platform"] == {}
        assert stats["errors_24h_by_platform"] == {}

    def test_get_stats_with_data(self, tmp_db):
        tmp_db.register_user(1, "alice", "Alice")
        tmp_db.register_user(2, "bob", "Bob")
        tmp_db.log_download(1, "tiktok", "url1")
        tmp_db.log_download(1, "tiktok", "url2")
        tmp_db.log_download(2, "youtube", "url3")

        stats = tmp_db.get_stats()
        assert stats["total_users"] == 2
        assert stats["total_downloads"] == 3
        assert stats["by_platform"]["tiktok"] == 2
        assert stats["by_platform"]["youtube"] == 1
        assert stats["active_24h"] == 2  # both users downloaded recently
        assert stats["first_seen"] is not None

    def test_multiple_users(self, tmp_db):
        for i in range(10):
            tmp_db.register_user(i, f"user{i}", f"Name{i}")
        assert tmp_db.get_user_count() == 10

    def test_get_user_count_zero(self, tmp_db):
        assert tmp_db.get_user_count() == 0

    def test_get_download_count_zero(self, tmp_db):
        assert tmp_db.get_download_count() == 0

    def test_get_broadcast_subscribed_user_ids(self, tmp_db):
        tmp_db.register_user(1, "alice", "Alice")
        tmp_db.register_user(2, "bob", "Bob")
        assert sorted(tmp_db.get_broadcast_subscribed_user_ids()) == [1, 2]

    def test_get_broadcast_subscribed_user_ids_empty(self, tmp_db):
        assert tmp_db.get_broadcast_subscribed_user_ids() == []

    def test_opted_out_user_excluded_from_broadcast_list(self, tmp_db):
        tmp_db.register_user(1, "alice", "Alice")
        tmp_db.register_user(2, "bob", "Bob")

        tmp_db.set_broadcast_opt_out(1, True)

        assert tmp_db.get_broadcast_subscribed_user_ids() == [2]

    def test_opt_out_can_be_reversed(self, tmp_db):
        tmp_db.register_user(1, "alice", "Alice")
        tmp_db.set_broadcast_opt_out(1, True)
        assert tmp_db.get_broadcast_subscribed_user_ids() == []

        tmp_db.set_broadcast_opt_out(1, False)
        assert tmp_db.get_broadcast_subscribed_user_ids() == [1]

    def test_new_users_are_subscribed_by_default(self, tmp_db):
        tmp_db.register_user(1, "alice", "Alice")
        assert tmp_db.get_broadcast_subscribed_user_ids() == [1]

    def test_get_user_display_names_prefers_username(self, tmp_db):
        tmp_db.register_user(1, "alice_w", "Alice")
        names = tmp_db.get_user_display_names([1])
        assert names == {1: "@alice_w"}

    def test_get_user_display_names_falls_back_to_first_name(self, tmp_db):
        tmp_db.register_user(2, None, "Bob")
        names = tmp_db.get_user_display_names([2])
        assert names == {2: "Bob"}

    def test_get_user_display_names_falls_back_to_id(self, tmp_db):
        tmp_db.register_user(3, None, None)
        names = tmp_db.get_user_display_names([3])
        assert names == {3: "3"}

    def test_get_user_display_names_ignores_unknown_ids(self, tmp_db):
        tmp_db.register_user(1, "alice_w", "Alice")
        names = tmp_db.get_user_display_names([1, 999])
        assert names == {1: "@alice_w"}

    def test_get_user_display_names_empty_input(self, tmp_db):
        assert tmp_db.get_user_display_names([]) == {}

    def test_save_and_get_callback(self, tmp_db):
        tmp_db.save_callback("token1", "http://example.com/1", "137", "video")
        
        cb = tmp_db.get_callback("token1")
        assert cb is not None
        assert cb["url"] == "http://example.com/1"
        assert cb["itag"] == "137"
        assert cb["type"] == "video"

    def test_get_nonexistent_callback(self, tmp_db):
        cb = tmp_db.get_callback("invalid")
        assert cb is None

    def test_delete_callback(self, tmp_db):
        tmp_db.save_callback("token1", "url", "137", "video")
        tmp_db.delete_callback("token1")
        
        cb = tmp_db.get_callback("token1")
        assert cb is None

    def test_save_callback_replace(self, tmp_db):
        tmp_db.save_callback("token1", "url1", "137", "video")
        tmp_db.save_callback("token1", "url2", "22", "audio")

        cb = tmp_db.get_callback("token1")
        assert cb["url"] == "url2"
        assert cb["itag"] == "22"

    def test_log_error(self, tmp_db):
        tmp_db.log_error("tiktok", "ValueError", "boom")

        row = tmp_db._conn.execute(
            "SELECT platform, error_type, message FROM errors"
        ).fetchone()
        assert row["platform"] == "tiktok"
        assert row["error_type"] == "ValueError"
        assert row["message"] == "boom"

    def test_get_stats_includes_error_rate_data(self, tmp_db):
        tmp_db.register_user(1, "alice", "Alice")
        tmp_db.log_download(1, "tiktok", "url1")
        tmp_db.log_error("tiktok", "ValueError", "parse failed")
        tmp_db.log_error("tiktok", "ValueError", "parse failed again")
        tmp_db.log_error("youtube", "TimeoutError", "slow")

        stats = tmp_db.get_stats()
        assert stats["downloads_24h_by_platform"]["tiktok"] == 1
        assert stats["errors_24h_by_platform"]["tiktok"] == 2
        assert stats["errors_24h_by_platform"]["youtube"] == 1
        assert "instagram" not in stats["errors_24h_by_platform"]

    def test_migration_adds_broadcast_opt_out_to_pre_existing_db(self, tmp_path):
        """Simulates opening a database created before broadcast_opt_out
        existed — the migration must add it without crashing or losing data."""
        db_path = str(tmp_path / "old_schema.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                first_name TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("INSERT INTO users (user_id, username, first_name) VALUES (5, 'old', 'User')")
        conn.commit()
        conn.close()

        db = BotDatabase(db_path=db_path)
        try:
            assert db.get_broadcast_subscribed_user_ids() == [5]
        finally:
            db.close()

    def test_save_and_get_playlist_state(self, tmp_db):
        urls = ["https://youtube.com/watch?v=a", "https://youtube.com/watch?v=b"]
        tmp_db.save_playlist_state("tok1", urls, total_count=5)

        state = tmp_db.get_playlist_state("tok1")
        assert state == {"video_urls": urls, "index_pos": 0, "total_count": 5}

    def test_get_playlist_state_missing_token(self, tmp_db):
        assert tmp_db.get_playlist_state("nope") is None

    def test_advance_playlist_state(self, tmp_db):
        urls = ["https://youtube.com/watch?v=a", "https://youtube.com/watch?v=b"]
        tmp_db.save_playlist_state("tok1", urls, total_count=2)

        state = tmp_db.advance_playlist_state("tok1")
        assert state["index_pos"] == 1

        state = tmp_db.advance_playlist_state("tok1")
        assert state["index_pos"] == 2

    def test_delete_playlist_state(self, tmp_db):
        tmp_db.save_playlist_state("tok1", ["u1"], total_count=1)
        tmp_db.delete_playlist_state("tok1")
        assert tmp_db.get_playlist_state("tok1") is None

    def test_cleanup_stale_state_removes_old_rows(self, tmp_db):
        tmp_db.save_callback("old", "url", "18", "video")
        tmp_db.save_playlist_state("oldpl", ["u1"], 1)
        # Backdate both rows past the cutoff
        tmp_db._conn.execute("UPDATE callbacks SET created_at = datetime('now', '-48 hours')")
        tmp_db._conn.execute("UPDATE playlist_state SET created_at = datetime('now', '-48 hours')")
        tmp_db._conn.commit()

        removed = tmp_db.cleanup_stale_state(max_age_hours=24)

        assert removed == {"callbacks": 1, "playlist_state": 1}
        assert tmp_db.get_callback("old") is None
        assert tmp_db.get_playlist_state("oldpl") is None

    def test_cleanup_stale_state_keeps_fresh_rows(self, tmp_db):
        tmp_db.save_callback("fresh", "url", "18", "video")
        tmp_db.save_playlist_state("freshpl", ["u1"], 1)

        removed = tmp_db.cleanup_stale_state(max_age_hours=24)

        assert removed == {"callbacks": 0, "playlist_state": 0}
        assert tmp_db.get_callback("fresh") is not None
        assert tmp_db.get_playlist_state("freshpl") is not None

    def test_callback_carries_playlist_token(self, tmp_db):
        tmp_db.save_callback("tok", "url", "18", "video", playlist_token="pl1")
        assert tmp_db.get_callback("tok")["playlist_token"] == "pl1"

    def test_callback_without_playlist_token(self, tmp_db):
        tmp_db.save_callback("tok", "url", "18", "video")
        assert tmp_db.get_callback("tok")["playlist_token"] is None
