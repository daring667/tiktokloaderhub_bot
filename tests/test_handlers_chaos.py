"""Tests for handlers/chaos.py: the Telegram side of the daily challenge."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

import handlers.chaos as chaos
from handlers.chaos import (
    register, run_daily_announcer, _announce, announcement_audience,
    notify_dethroned, current_leader,
)
from services.chaos.events import CATALOGUE_VERSION, replay_chain
from services.chaos.seed import day_key, shift_day_key
from services.chaos.storage import ChaosStorage
from _helpers import FakeApp, make_message, make_callback


@pytest.fixture()
def store(tmp_path):
    storage = ChaosStorage(db_path=str(tmp_path / "chaos.db"))
    yield storage
    storage.close()


@pytest.fixture()
def handlers(store):
    """Returns the four handlers in registration order."""
    app = FakeApp()
    db = MagicMock()
    db.get_broadcast_subscribed_user_ids.return_value = [111, 222]
    register(app, db, storage=store)
    chaos_h, top_h, streak_h, result_h = app.message_handlers
    return {
        "chaos": chaos_h, "top": top_h, "streak": streak_h,
        "result": result_h, "db": db,
        "mute": app.callback_handlers[0],
    }


def _run_message(apples=8, score=100, ms=60000, day=None):
    """A message carrying a genuine run for the current game day."""
    day = day or day_key()
    message = make_message("")
    message.web_app_data = MagicMock()
    message.web_app_data.data = json.dumps({
        "v": 1, "cat": CATALOGUE_VERSION, "day": day,
        "apples": apples, "score": score, "ms": ms,
        "events": replay_chain(day, apples),
    })
    return message


class TestChaosCommand:
    @pytest.mark.asyncio
    async def test_offers_a_web_app_button(self, handlers):
        message = make_message("/chaos")
        await handlers["chaos"](MagicMock(), message)

        markup = message.reply.await_args.kwargs["reply_markup"]
        button = markup.keyboard[0][0]
        assert button.web_app is not None
        assert button.web_app.url.startswith("https://")

    @pytest.mark.asyncio
    async def test_mentions_todays_key(self, handlers):
        message = make_message("/chaos")
        await handlers["chaos"](MagicMock(), message)
        assert day_key() in message.reply.await_args.args[0]

    @pytest.mark.asyncio
    async def test_shows_todays_result_once_played(self, handlers, store):
        store.save_run(111, "Test", {
            "day_key": day_key(), "apples": 9, "score": 137,
            "duration_ms": 1000, "events": [], "cleared": True,
        })
        message = make_message("/chaos")
        await handlers["chaos"](MagicMock(), message)
        assert "137" in message.reply.await_args.args[0]


class TestTopCommand:
    @pytest.mark.asyncio
    async def test_empty_day_reads_as_an_invitation(self, handlers):
        message = make_message("/top")
        await handlers["top"](MagicMock(), message)
        assert "никто не играл" in message.reply.await_args.args[0]

    @pytest.mark.asyncio
    async def test_lists_players_by_score(self, handlers, store):
        today = day_key()
        for user_id, name, score in [(1, "Аня", 100), (2, "Боря", 300)]:
            store.save_run(user_id, name, {
                "day_key": today, "apples": 8, "score": score,
                "duration_ms": 1000, "events": [], "cleared": True,
            })

        message = make_message("/top")
        await handlers["top"](MagicMock(), message)
        text = message.reply.await_args.args[0]
        assert text.index("Боря") < text.index("Аня")

    @pytest.mark.asyncio
    async def test_escapes_html_in_names(self, handlers, store):
        """A display name is user-controlled and goes into an HTML message."""
        store.save_run(1, "<b>hax</b>", {
            "day_key": day_key(), "apples": 8, "score": 10,
            "duration_ms": 1000, "events": [], "cleared": True,
        })
        message = make_message("/top")
        await handlers["top"](MagicMock(), message)
        assert "&lt;b&gt;hax&lt;/b&gt;" in message.reply.await_args.args[0]


class TestStreakCommand:
    @pytest.mark.asyncio
    async def test_reports_zero_for_a_newcomer(self, handlers):
        message = make_message("/streak")
        await handlers["streak"](MagicMock(), message)
        assert "0" in message.reply.await_args.args[0]

    @pytest.mark.asyncio
    async def test_warns_when_a_streak_is_about_to_lapse(self, handlers, store):
        store.bump_streak(111, shift_day_key(day_key(), -1))
        message = make_message("/streak")
        await handlers["streak"](MagicMock(), message)
        assert "оборвётся" in message.reply.await_args.args[0]


class TestResultSubmission:
    @pytest.mark.asyncio
    async def test_stores_a_valid_run(self, handlers, store):
        await handlers["result"](MagicMock(), _run_message(apples=8, score=100))
        assert store.count_submissions(111, day_key()) == 1

    @pytest.mark.asyncio
    async def test_clearing_the_day_starts_a_streak(self, handlers, store):
        await handlers["result"](MagicMock(), _run_message(apples=7, score=90))
        assert store.get_streak(111)["current"] == 1

    @pytest.mark.asyncio
    async def test_falling_short_does_not_start_a_streak(self, handlers, store):
        await handlers["result"](MagicMock(), _run_message(apples=6, score=70))
        assert store.get_streak(111)["current"] == 0

    @pytest.mark.asyncio
    async def test_reports_how_many_apples_were_missing(self, handlers):
        message = _run_message(apples=5, score=60)
        await handlers["result"](MagicMock(), message)
        assert "не хватило 2" in message.reply.await_args.args[0]

    @pytest.mark.asyncio
    async def test_rejected_run_is_not_stored(self, handlers, store):
        message = _run_message(apples=2, score=99999)
        await handlers["result"](MagicMock(), message)

        assert "не принят" in message.reply.await_args.args[0]
        assert store.count_submissions(111, day_key()) == 0

    @pytest.mark.asyncio
    async def test_forged_event_chain_is_rejected(self, handlers, store):
        message = _run_message(apples=8, score=100)
        payload = json.loads(message.web_app_data.data)
        payload["events"] = ["l:reverse"] * 8   # claim a legendary every apple
        message.web_app_data.data = json.dumps(payload)

        await handlers["result"](MagicMock(), message)
        assert store.count_submissions(111, day_key()) == 0

    @pytest.mark.asyncio
    async def test_daily_submission_cap_is_enforced(self, handlers, store):
        for _ in range(20):
            await handlers["result"](MagicMock(), _run_message(apples=1, score=10))
        message = _run_message(apples=1, score=10)
        await handlers["result"](MagicMock(), message)

        assert "не принят" in message.reply.await_args.args[0]
        assert store.count_submissions(111, day_key()) == 20

    @pytest.mark.asyncio
    async def test_announces_a_personal_best(self, handlers):
        await handlers["result"](MagicMock(), _run_message(apples=3, score=30))
        message = _run_message(apples=8, score=110)
        await handlers["result"](MagicMock(), message)
        assert "рекорд" in message.reply.await_args.args[0]


class TestAnnouncementAudience:
    """Who gets the post, and why it is not simply everyone.

    The first real announcement failed for four people with PEER_ID_INVALID.
    They had reached the users table by dropping a link in a group the bot
    sits in, and Telegram does not let a bot open a private chat with someone
    who never started it — the HTTP Bot API returns "chat not found" for the
    same ids, so no change of transport helps. Only people who opened the
    game, which is private-chat only, can actually be reached.
    """

    def _db(self, subscribed):
        db = MagicMock()
        db.get_broadcast_subscribed_user_ids.return_value = list(subscribed)
        return db

    def test_only_people_who_opened_the_game(self, store):
        store.remember_player(1, "Аня")
        store.remember_player(2, "Боря")
        # 3 never opened it — a group-only user
        assert announcement_audience(self._db([1, 2, 3]), store) == [1, 2]

    def test_opting_out_still_wins(self, store):
        store.remember_player(1, "Аня")
        store.remember_player(2, "Боря")
        assert announcement_audience(self._db([1]), store) == [1]

    def test_nobody_has_played_yet(self, store):
        assert announcement_audience(self._db([1, 2, 3]), store) == []

    def test_without_a_database_everyone_known_is_included(self, store):
        store.remember_player(7, "Аня")
        assert announcement_audience(None, store) == [7]

    def test_a_player_is_recorded_once(self, store):
        store.remember_player(1, "Аня")
        store.remember_player(1, "Аня Б.")
        assert store.get_known_players() == [1]


class TestDailyAnnouncement:
    @staticmethod
    def _client():
        client = MagicMock()
        client.send_message = AsyncMock()
        return client

    @staticmethod
    def _db(user_ids):
        db = MagicMock()
        db.get_broadcast_subscribed_user_ids.return_value = list(user_ids)
        return db

    @staticmethod
    async def _poll(client, db, store, seconds=0.08):
        task = asyncio.create_task(run_daily_announcer(client, db, store))
        await asyncio.sleep(seconds)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_sends_to_players_only(self, store):
        for uid in (1, 2):
            store.remember_player(uid, "Игрок")
        client = self._client()

        await _announce(client, self._db([1, 2, 3]), store, day_key())
        assert client.send_message.await_count == 2

    @pytest.mark.asyncio
    async def test_names_yesterdays_winner(self, store):
        store.remember_player(1, "Аня")
        store.save_run(9, "Вера", {
            "day_key": shift_day_key(day_key(), -1), "apples": 12, "score": 240,
            "duration_ms": 1000, "events": [], "cleared": True,
        })
        client = self._client()

        await _announce(client, self._db([1]), store, day_key())
        assert "Вера" in client.send_message.await_args.args[1]

    @pytest.mark.asyncio
    async def test_one_failure_does_not_stop_the_rest(self, store):
        for uid in (1, 2, 3):
            store.remember_player(uid, "Игрок")
        client = self._client()
        client.send_message = AsyncMock(side_effect=[Exception("blocked"), None, None])

        await _announce(client, self._db([1, 2, 3]), store, day_key())
        assert client.send_message.await_count == 3

    @pytest.mark.asyncio
    async def test_first_ever_start_stays_quiet(self, store, monkeypatch):
        """Deploying at 3pm must not fire the daily post right then."""
        monkeypatch.setattr(chaos, "ANNOUNCE_POLL_SECONDS", 0.01)
        store.remember_player(1, "Аня")
        client = self._client()

        await self._poll(client, self._db([1]), store)

        client.send_message.assert_not_awaited()
        assert store.get_meta("last_announced_day") == day_key()

    @pytest.mark.asyncio
    async def test_announces_once_and_not_again(self, store, monkeypatch):
        monkeypatch.setattr(chaos, "ANNOUNCE_POLL_SECONDS", 0.01)
        store.remember_player(1, "Аня")
        store.set_meta("last_announced_day", shift_day_key(day_key(), -1))
        client = self._client()

        await self._poll(client, self._db([1]), store)

        assert client.send_message.await_count == 1
        assert store.get_meta("last_announced_day") == day_key()

    @pytest.mark.asyncio
    async def test_a_restart_after_the_rollover_still_posts(self, store, monkeypatch):
        """The bot being down at noon must not silently skip the day."""
        monkeypatch.setattr(chaos, "ANNOUNCE_POLL_SECONDS", 0.01)
        store.remember_player(1, "Аня")
        store.set_meta("last_announced_day", shift_day_key(day_key(), -1))
        client = self._client()

        await self._poll(client, self._db([1]), store, seconds=0.05)

        assert client.send_message.await_count == 1


class TestAnnouncementSwitch:
    """CHAOS_ANNOUNCE turns the daily post off without removing it."""

    @staticmethod
    def _client():
        client = MagicMock()
        client.send_message = AsyncMock()
        return client

    @staticmethod
    def _db(user_ids=(1,)):
        db = MagicMock()
        db.get_broadcast_subscribed_user_ids.return_value = list(user_ids)
        return db

    @staticmethod
    async def _poll(client, db, store, seconds=0.05):
        task = asyncio.create_task(run_daily_announcer(client, db, store))
        await asyncio.sleep(seconds)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_disabled_sends_nothing(self, store, monkeypatch):
        monkeypatch.setenv("CHAOS_ANNOUNCE", "0")
        monkeypatch.setattr(chaos, "ANNOUNCE_POLL_SECONDS", 0.01)
        store.remember_player(1, "Аня")
        store.set_meta("last_announced_day", shift_day_key(day_key(), -1))
        client = self._client()

        await self._poll(client, self._db(), store)
        client.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disabled_still_records_the_day(self, store, monkeypatch):
        """Otherwise switching it back on fires a post immediately, at
        whatever hour that happens to be."""
        monkeypatch.setenv("CHAOS_ANNOUNCE", "0")
        monkeypatch.setattr(chaos, "ANNOUNCE_POLL_SECONDS", 0.01)
        store.set_meta("last_announced_day", shift_day_key(day_key(), -1))

        await self._poll(self._client(), self._db(), store)
        assert store.get_meta("last_announced_day") == day_key()

    @pytest.mark.asyncio
    async def test_switching_back_on_waits_for_the_next_rollover(self, store, monkeypatch):
        monkeypatch.setattr(chaos, "ANNOUNCE_POLL_SECONDS", 0.01)
        store.remember_player(1, "Аня")
        store.set_meta("last_announced_day", shift_day_key(day_key(), -1))

        monkeypatch.setenv("CHAOS_ANNOUNCE", "0")
        await self._poll(self._client(), self._db(), store)

        monkeypatch.setenv("CHAOS_ANNOUNCE", "1")
        client = self._client()
        await self._poll(client, self._db(), store)
        client.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enabled_by_default(self, store, monkeypatch):
        monkeypatch.delenv("CHAOS_ANNOUNCE", raising=False)
        monkeypatch.setattr(chaos, "ANNOUNCE_POLL_SECONDS", 0.01)
        store.remember_player(1, "Аня")
        store.set_meta("last_announced_day", shift_day_key(day_key(), -1))
        client = self._client()

        await self._poll(client, self._db(), store)
        assert client.send_message.await_count == 1

    @pytest.mark.parametrize("value,expected", [
        ("0", False), ("false", False), ("no", False), ("FALSE", False),
        ("1", True), ("true", True), ("", True),
    ])
    def test_switch_parsing(self, value, expected, monkeypatch):
        monkeypatch.setenv("CHAOS_ANNOUNCE", value)
        assert chaos.announcements_enabled() is expected


class TestStaleClientReply:
    @pytest.mark.asyncio
    async def test_tells_the_player_to_reopen_instead_of_blaming_them(self, handlers, store):
        message = _run_message()
        payload = json.loads(message.web_app_data.data)
        payload["cat"] = 0
        message.web_app_data.data = json.dumps(payload)

        await handlers["result"](MagicMock(), message)

        text = message.reply.await_args.args[0]
        assert "обновилась" in text
        assert "не принят" not in text          # no hint of foul play
        assert store.count_submissions(111, day_key()) == 0


class TestDethroneNotice:
    """Telling the former leader they have been passed.

    The whole mechanic hangs on firing only when the top spot changes hands.
    Most of these tests are about the cases where nothing should be sent —
    a notification that arrives when it shouldn't is worse than none at all,
    because people mute the bot rather than complain.
    """

    @staticmethod
    def _client():
        client = MagicMock()
        client.send_message = AsyncMock()
        return client

    @staticmethod
    def _db(subscribed=(1, 2, 3, 111)):
        db = MagicMock()
        db.get_broadcast_subscribed_user_ids.return_value = list(subscribed)
        return db

    @staticmethod
    def _save(store, user_id, name, score, day=None):
        store.save_run(user_id, name, {
            "day_key": day or day_key(), "apples": 8, "score": score,
            "duration_ms": 60000, "events": [], "cleared": True,
        })

    @pytest.mark.asyncio
    async def test_the_passed_player_is_told(self, store):
        today = day_key()
        self._save(store, 1, "Аня", 100)
        before = current_leader(store, today)
        self._save(store, 2, "Боря", 300)

        client = self._client()
        assert await notify_dethroned(client, store, before, today) is True

        target, text = client.send_message.await_args.args
        assert target == 1
        assert "Боря" in text and "300" in text and "100" in text

    @pytest.mark.asyncio
    async def test_improving_your_own_lead_tells_nobody(self, store):
        """The commonest case by far: one person grinding attempts. If this
        pinged anyone the feature would be unusable."""
        today = day_key()
        self._save(store, 1, "Аня", 100)
        before = current_leader(store, today)
        self._save(store, 1, "Аня", 400)

        client = self._client()
        assert await notify_dethroned(client, store, before, today) is False
        client.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_first_run_of_the_day_tells_nobody(self, store):
        today = day_key()
        before = current_leader(store, today)      # nobody yet
        self._save(store, 1, "Аня", 100)

        client = self._client()
        assert await notify_dethroned(client, store, before, today) is False

    @pytest.mark.asyncio
    async def test_a_run_that_does_not_take_the_lead_tells_nobody(self, store):
        today = day_key()
        self._save(store, 1, "Аня", 500)
        before = current_leader(store, today)
        self._save(store, 2, "Боря", 100)

        client = self._client()
        assert await notify_dethroned(client, store, before, today) is False

    @pytest.mark.asyncio
    async def test_someone_who_muted_these_is_left_alone(self, store):
        today = day_key()
        self._save(store, 1, "Аня", 100)
        store.set_notifications(1, False)
        before = current_leader(store, today)
        self._save(store, 2, "Боря", 300)

        client = self._client()
        assert await notify_dethroned(client, store, before, today) is False
        client.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_muting_is_separate_from_the_broadcast_opt_out(self, store):
        """Refusing the daily mailing is not refusing to hear that you lost
        the lead in a game you are playing right now. Conflating them meant
        one setting silently killed the other, with no way back except
        resubscribing to the mailing you did not want."""
        today = day_key()
        self._save(store, 1, "Аня", 100)
        before = current_leader(store, today)
        self._save(store, 2, "Боря", 300)

        # Opted out of broadcasts, never muted the game.
        db = self._db(subscribed=[])
        client = self._client()
        assert await notify_dethroned(client, store, before, today) is True
        assert db.get_broadcast_subscribed_user_ids() == []

    @pytest.mark.asyncio
    async def test_a_new_player_is_not_muted_by_default(self, store):
        assert store.wants_notifications(4242) is True

    @pytest.mark.asyncio
    async def test_muting_can_be_undone(self, store):
        store.set_notifications(1, False)
        assert store.wants_notifications(1) is False
        store.set_notifications(1, True)
        assert store.wants_notifications(1) is True

    @pytest.mark.asyncio
    async def test_the_notice_carries_the_mute_button(self, store):
        today = day_key()
        self._save(store, 1, "Аня", 100)
        before = current_leader(store, today)
        self._save(store, 2, "Боря", 300)

        client = self._client()
        await notify_dethroned(client, store, before, today)
        markup = client.send_message.await_args.kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].callback_data == "chaos_mute"

    @pytest.mark.asyncio
    async def test_pressing_mute_stops_further_notices(self, handlers, store):
        callback = make_callback("chaos_mute", user_id=1)
        await handlers["mute"](MagicMock(), callback)

        assert store.wants_notifications(1) is False
        callback.answer.assert_awaited()

    @pytest.mark.asyncio
    async def test_a_failed_send_is_swallowed(self, store):
        """A blocked player must not break the submission of the person who
        just overtook them."""
        today = day_key()
        self._save(store, 1, "Аня", 100)
        before = current_leader(store, today)
        self._save(store, 2, "Боря", 300)

        client = self._client()
        client.send_message = AsyncMock(side_effect=Exception("blocked"))
        assert await notify_dethroned(client, store, before, today) is False

    @pytest.mark.asyncio
    async def test_the_name_is_escaped(self, store):
        today = day_key()
        self._save(store, 1, "Аня", 100)
        before = current_leader(store, today)
        self._save(store, 2, "<b>hax</b>", 300)

        client = self._client()
        await notify_dethroned(client, store, before, today)
        assert "&lt;b&gt;hax&lt;/b&gt;" in client.send_message.await_args.args[1]

    @pytest.mark.asyncio
    async def test_submitting_a_leading_run_notifies_and_says_so(self, handlers, store):
        """End to end through the result handler."""
        self._save(store, 1, "Аня", 10)
        client = MagicMock()
        client.send_message = AsyncMock()

        message = _run_message(apples=9, score=140)
        await handlers["result"](client, message)

        assert client.send_message.await_count == 1
        assert client.send_message.await_args.args[0] == 1
        assert "первое место" in message.reply.await_args.args[0]

    @pytest.mark.asyncio
    async def test_a_losing_run_notifies_nobody(self, handlers, store):
        self._save(store, 1, "Аня", 9999)
        client = MagicMock()
        client.send_message = AsyncMock()

        await handlers["result"](client, _run_message(apples=8, score=100))
        client.send_message.assert_not_awaited()
