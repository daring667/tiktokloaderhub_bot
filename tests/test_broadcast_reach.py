"""Broadcast reachability.

Background: the first daily announcement failed for four of thirteen people
with PEER_ID_INVALID. They had reached the users table by dropping a link in
a group the bot sits in, and Telegram will not let a bot open a private chat
with someone who never started it — the HTTP Bot API answers "chat not
found" for the same ids, so no change of transport helps. Those attempts
fail identically every time, so the list stops including them.
"""
import pytest

from services.utils.broadcast import is_permanent_failure


class TestFailureClassification:
    @pytest.mark.parametrize("error", [
        "Telegram says: [400 PEER_ID_INVALID] - The peer id being used is invalid",
        "Telegram says: [400 USER_IS_BLOCKED] - The user blocked you",
        "Bad Request: chat not found",
        "Forbidden: bot was blocked by the user",
        "[400 INPUT_USER_DEACTIVATED] - The user is deactivated",
    ])
    def test_permanent_failures_are_recognised(self, error):
        assert is_permanent_failure(error) is True

    @pytest.mark.parametrize("error", [
        "Telegram says: [420 FLOOD_WAIT_X] - A wait of 30 seconds is required",
        "ConnectionError: connection reset by peer",
        "TimeoutError",
        "[500 INTERNAL_SERVER_ERROR]",
    ])
    def test_transient_failures_are_left_alone(self, error):
        """A flood wait or a dropped connection says nothing about whether
        the user is reachable — dropping them would be a real loss."""
        assert is_permanent_failure(error) is False

    def test_no_error_is_not_a_failure(self):
        assert is_permanent_failure(None) is False
        assert is_permanent_failure("") is False


class TestReachabilityInDatabase:
    def test_everyone_starts_reachable(self, tmp_db):
        tmp_db.register_user(1, "anya", "Аня")
        assert tmp_db.get_broadcast_subscribed_user_ids() == [1]
        assert tmp_db.count_unreachable() == 0

    def test_marking_removes_from_the_list(self, tmp_db):
        for uid in (1, 2, 3):
            tmp_db.register_user(uid, f"u{uid}", f"U{uid}")
        tmp_db.mark_broadcast_unreachable([2])

        assert tmp_db.get_broadcast_subscribed_user_ids() == [1, 3]
        assert tmp_db.count_unreachable() == 1

    def test_marking_nobody_changes_nothing(self, tmp_db):
        tmp_db.register_user(1, "anya", "Аня")
        assert tmp_db.mark_broadcast_unreachable([]) == 0
        assert tmp_db.get_broadcast_subscribed_user_ids() == [1]

    def test_starting_the_bot_makes_them_reachable_again(self, tmp_db):
        tmp_db.register_user(1, "anya", "Аня")
        tmp_db.mark_broadcast_unreachable([1])
        assert tmp_db.get_broadcast_subscribed_user_ids() == []

        tmp_db.mark_broadcast_reachable(1)
        assert tmp_db.get_broadcast_subscribed_user_ids() == [1]

    def test_opting_out_and_unreachable_are_separate(self, tmp_db):
        """Someone can be reachable but uninterested, or interested but
        unreachable; conflating the two would lose one of the states."""
        for uid in (1, 2):
            tmp_db.register_user(uid, f"u{uid}", f"U{uid}")
        tmp_db.set_broadcast_opt_out(1, True)
        tmp_db.mark_broadcast_unreachable([2])

        assert tmp_db.get_broadcast_subscribed_user_ids() == []
        # Becoming reachable again must not resubscribe someone who opted out.
        tmp_db.mark_broadcast_reachable(1)
        assert tmp_db.get_broadcast_subscribed_user_ids() == []

    def test_registering_again_does_not_clear_the_mark(self, tmp_db):
        """register_user fires on group activity too, which proves nothing
        about private reachability — only /start in a DM does."""
        tmp_db.register_user(1, "anya", "Аня")
        tmp_db.mark_broadcast_unreachable([1])
        tmp_db.register_user(1, "anya", "Аня")
        assert tmp_db.get_broadcast_subscribed_user_ids() == []
