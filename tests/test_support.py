"""Tests for the support channel: the rules, the storage and the ticket card."""
import pytest

from handlers import support as handler
from services import support


class TestValidateReport:

    def test_a_real_description_is_accepted(self):
        assert support.validate_report("  видео не приходит  ") == "видео не приходит"

    @pytest.mark.parametrize("text", ["", "   ", "ой", None])
    def test_too_short_is_rejected(self, text):
        with pytest.raises(support.ReportRejected):
            support.validate_report(text)

    def test_too_long_is_rejected(self):
        with pytest.raises(support.ReportRejected):
            support.validate_report("x" * (support.MAX_REPORT_LENGTH + 1))

    def test_the_longest_allowed_report_still_passes(self):
        text = "x" * support.MAX_REPORT_LENGTH
        assert support.validate_report(text) == text

    def test_the_reason_is_shown_to_the_person(self):
        """The message is the user-facing explanation, so it must say something."""
        with pytest.raises(support.ReportRejected) as e:
            support.validate_report("x")
        assert str(e.value).strip()


class TestQuota:

    def test_a_first_report_is_allowed(self):
        support.check_quota(0)

    def test_the_limit_is_on_open_tickets(self):
        support.check_quota(support.MAX_OPEN_TICKETS_PER_USER - 1)
        with pytest.raises(support.ReportRejected):
            support.check_quota(support.MAX_OPEN_TICKETS_PER_USER)


class TestStatuses:

    def test_creating_a_ticket_sends_no_status_notice(self):
        """They were just told the ticket number; repeating it is noise."""
        assert support.status_notice(support.STATUS_OPEN) is None

    @pytest.mark.parametrize("status", [
        support.STATUS_INVESTIGATING, support.STATUS_FIXED, support.STATUS_CLOSED])
    def test_every_other_status_tells_the_reporter_something(self, status):
        assert support.status_notice(status)

    @pytest.mark.parametrize("status", support.STATUSES)
    def test_every_status_has_a_label(self, status):
        assert support.status_label(status)

    def test_an_unknown_stored_status_reads_as_open(self):
        assert support.normalize_status("sideways") == support.STATUS_OPEN
        assert support.normalize_status(None) == support.STATUS_OPEN

    def test_open_and_investigating_count_as_open(self):
        assert support.is_open(support.STATUS_OPEN)
        assert support.is_open(support.STATUS_INVESTIGATING)
        assert not support.is_open(support.STATUS_FIXED)
        assert not support.is_open(support.STATUS_CLOSED)


class TestTicketStorage:

    def test_a_ticket_gets_a_number_and_starts_open(self, tmp_db):
        ticket_id = tmp_db.create_ticket(7, "не качает")
        ticket = tmp_db.get_ticket(ticket_id)
        assert ticket["user_id"] == 7
        assert ticket["message"] == "не качает"
        assert ticket["status"] == support.STATUS_OPEN

    def test_numbers_do_not_repeat(self, tmp_db):
        first = tmp_db.create_ticket(7, "раз")
        second = tmp_db.create_ticket(7, "два")
        assert first != second

    def test_context_is_stored_with_the_ticket(self, tmp_db):
        ticket_id = tmp_db.create_ticket(
            7, "ошибка", platform="youtube", url="https://y/1",
            error_type="ValueError")
        ticket = tmp_db.get_ticket(ticket_id)
        assert ticket["platform"] == "youtube"
        assert ticket["url"] == "https://y/1"
        assert ticket["error_type"] == "ValueError"

    def test_a_missing_ticket_is_none_rather_than_an_error(self, tmp_db):
        assert tmp_db.get_ticket(999) is None

    def test_status_changes_are_stored(self, tmp_db):
        ticket_id = tmp_db.create_ticket(7, "не качает")
        assert tmp_db.set_ticket_status(ticket_id, support.STATUS_FIXED) is True
        assert tmp_db.get_ticket(ticket_id)["status"] == support.STATUS_FIXED

    def test_updating_a_missing_ticket_reports_failure(self, tmp_db):
        assert tmp_db.set_ticket_status(999, support.STATUS_FIXED) is False

    def test_open_tickets_are_counted_per_user(self, tmp_db):
        tmp_db.create_ticket(7, "раз")
        tmp_db.create_ticket(7, "два")
        tmp_db.create_ticket(8, "чужой")
        assert tmp_db.count_open_tickets(7) == 2
        assert tmp_db.count_open_tickets(8) == 1

    def test_a_closed_ticket_frees_up_the_quota(self, tmp_db):
        ticket_id = tmp_db.create_ticket(7, "раз")
        tmp_db.set_ticket_status(ticket_id, support.STATUS_FIXED)
        assert tmp_db.count_open_tickets(7) == 0

    def test_listing_can_be_narrowed_to_open_ones(self, tmp_db):
        closed = tmp_db.create_ticket(7, "старое")
        tmp_db.set_ticket_status(closed, support.STATUS_CLOSED)
        open_id = tmp_db.create_ticket(7, "новое")
        listed = tmp_db.list_tickets(
            statuses=(support.STATUS_OPEN, support.STATUS_INVESTIGATING))
        assert [t["id"] for t in listed] == [open_id]

    def test_replies_are_kept_in_order(self, tmp_db):
        ticket_id = tmp_db.create_ticket(7, "не качает")
        tmp_db.add_reply(ticket_id, "admin", "смотрю")
        tmp_db.add_reply(ticket_id, "admin", "починил")
        assert [r["message"] for r in tmp_db.get_replies(ticket_id)] == [
            "смотрю", "починил"]

    def test_the_recipient_is_recoverable_from_the_ticket_alone(self, tmp_db):
        """Admin replies are addressed from this row, never from a payload."""
        ticket_id = tmp_db.create_ticket(4242, "не качает")
        assert tmp_db.get_ticket(ticket_id)["user_id"] == 4242


class TestFailureContext:

    def test_nothing_is_remembered_at_first(self, tmp_db):
        assert tmp_db.get_failure_context(7) is None

    def test_the_last_failure_is_remembered(self, tmp_db):
        tmp_db.remember_failure(7, "youtube", "https://y/1", "ValueError")
        context = tmp_db.get_failure_context(7)
        assert context["platform"] == "youtube"
        assert context["url"] == "https://y/1"

    def test_only_the_latest_is_kept(self, tmp_db):
        tmp_db.remember_failure(7, "youtube", "https://y/1", "ValueError")
        tmp_db.remember_failure(7, "tiktok", "https://t/2", "TimeoutError")
        assert tmp_db.get_failure_context(7)["platform"] == "tiktok"

    def test_context_is_per_user(self, tmp_db):
        tmp_db.remember_failure(7, "youtube", "https://y/1", "ValueError")
        assert tmp_db.get_failure_context(8) is None


class TestPendingInput:

    def test_nothing_pending_at_first(self, tmp_db):
        assert tmp_db.get_pending(7) is None

    def test_a_pending_report_is_remembered(self, tmp_db):
        tmp_db.set_pending(7, "report")
        assert tmp_db.get_pending(7)["action"] == "report"

    def test_a_pending_reply_carries_its_ticket(self, tmp_db):
        tmp_db.set_pending(1, "reply", 42)
        assert tmp_db.get_pending(1)["ticket_id"] == 42

    def test_setting_again_replaces_the_previous_one(self, tmp_db):
        tmp_db.set_pending(1, "reply", 42)
        tmp_db.set_pending(1, "report")
        pending = tmp_db.get_pending(1)
        assert pending["action"] == "report"
        assert pending["ticket_id"] is None

    def test_clearing_works(self, tmp_db):
        tmp_db.set_pending(7, "report")
        tmp_db.clear_pending(7)
        assert tmp_db.get_pending(7) is None

    def test_pending_survives_a_restart(self, tmp_db):
        """Someone mid-report must not lose what they are about to send."""
        from services.database import BotDatabase
        tmp_db.set_pending(7, "report")
        path = tmp_db.db_path
        tmp_db.close()
        reopened = BotDatabase(path)
        try:
            assert reopened.get_pending(7)["action"] == "report"
        finally:
            reopened.close()


class TestTicketCard:

    def _ticket(self, **over):
        base = {"id": 12, "user_id": 7, "status": support.STATUS_OPEN,
                "message": "не качает", "platform": "youtube",
                "url": "https://y/1", "error_type": "ValueError"}
        base.update(over)
        return base

    def test_card_shows_number_status_and_context(self):
        text = handler.ticket_card(self._ticket(), "@someone")
        assert "#12" in text
        assert support.status_label(support.STATUS_OPEN) in text
        assert "youtube" in text
        assert "не качает" in text

    def test_card_survives_a_ticket_with_no_context(self):
        text = handler.ticket_card(
            self._ticket(platform=None, url=None, error_type=None), "@someone")
        assert "#12" in text

    def test_user_text_is_escaped(self):
        """A report is user input and the card is sent as HTML."""
        text = handler.ticket_card(self._ticket(message="<b>oops</b>"), "@someone")
        assert "<b>oops</b>" not in text
        assert "&lt;b&gt;oops&lt;/b&gt;" in text

    def test_an_unknown_stored_status_still_renders(self):
        text = handler.ticket_card(self._ticket(status="sideways"), "@someone")
        assert support.status_label(support.STATUS_OPEN) in text

    def test_buttons_cover_reply_and_every_closing_status(self):
        rows = handler.ticket_markup(12).inline_keyboard
        data = [b.callback_data for row in rows for b in row]
        assert any(d.startswith("sup|reply|12") for d in data)
        for status in (support.STATUS_INVESTIGATING, support.STATUS_FIXED,
                       support.STATUS_CLOSED):
            assert f"sup|st|12|{status}" in data

    def test_callback_payloads_fit_telegrams_limit(self):
        rows = handler.ticket_markup(9999999).inline_keyboard
        for row in rows:
            for button in row:
                assert len(button.callback_data.encode("utf-8")) <= 64

    def test_the_report_button_starts_a_new_report(self):
        markup = handler.report_button()
        assert markup.inline_keyboard[0][0].callback_data == "sup|new"
