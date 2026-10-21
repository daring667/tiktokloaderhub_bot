"""Rules for the support channel: statuses, limits and what a report may say.

Free of SQLite and Pyrogram so the rules can be tested on their own. Storage
lives in `services/database.py`, the screens in `handlers/support.py`.
"""

STATUS_OPEN = "open"
STATUS_INVESTIGATING = "investigating"
STATUS_FIXED = "fixed"
STATUS_CLOSED = "closed"

STATUSES = (STATUS_OPEN, STATUS_INVESTIGATING, STATUS_FIXED, STATUS_CLOSED)

# Shown to the admin on the ticket card.
STATUS_LABELS = {
    STATUS_OPEN: "🆕 Новый",
    STATUS_INVESTIGATING: "🔍 Разбираюсь",
    STATUS_FIXED: "✅ Исправлено",
    STATUS_CLOSED: "📁 Закрыт",
}

# What the reporter is told when the status changes. Nothing is sent for
# STATUS_OPEN: that is the ticket being created, which they already know.
STATUS_NOTICES = {
    STATUS_INVESTIGATING: "🔍 Разбираюсь с твоей проблемой.",
    STATUS_FIXED: "✅ Проблема исправлена. Попробуй ещё раз.",
    STATUS_CLOSED: "📁 Обращение закрыто.",
}

# A report has to fit a Telegram message once the context is added around it,
# and a ticket nobody can read helps no one.
MIN_REPORT_LENGTH = 5
MAX_REPORT_LENGTH = 2000

# How long "the next message is a report" stays true. Someone who taps the
# button and wanders off must not have tomorrow's video link swallowed as a
# bug report, so the prompt expires rather than waiting forever.
PENDING_TTL_MINUTES = 30

# Finished tickets are kept this long so a reporter can still be answered
# about them, then swept with the rest of the stale state.
TICKET_RETENTION_DAYS = 30

# How many tickets one person may open before they have to wait. The limit is
# on *open* tickets rather than on a time window: someone with a real problem
# should not be timed out, but nobody needs ten unanswered tickets either.
MAX_OPEN_TICKETS_PER_USER = 5


class ReportRejected(Exception):
    """A report that should not become a ticket, with a reason to show."""


def validate_report(text: str | None) -> str:
    """Return the text to store, or raise `ReportRejected` explaining why not."""
    cleaned = (text or "").strip()
    if len(cleaned) < MIN_REPORT_LENGTH:
        raise ReportRejected(
            "Слишком короткое описание. Напиши, что именно пошло не так — "
            "хотя бы несколько слов."
        )
    if len(cleaned) > MAX_REPORT_LENGTH:
        raise ReportRejected(
            f"Слишком длинное описание (максимум {MAX_REPORT_LENGTH} символов). "
            "Опиши главное покороче."
        )
    return cleaned


def check_quota(open_tickets: int) -> None:
    """Raise `ReportRejected` when the person already has too many open."""
    if open_tickets >= MAX_OPEN_TICKETS_PER_USER:
        raise ReportRejected(
            "У тебя уже несколько открытых обращений. Дождись ответа по ним, "
            "прежде чем создавать новое."
        )


def is_open(status: str) -> bool:
    return status in (STATUS_OPEN, STATUS_INVESTIGATING)


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def status_notice(status: str) -> str | None:
    """What to tell the reporter, or None when there is nothing worth sending."""
    return STATUS_NOTICES.get(status)


def normalize_status(status: str | None) -> str:
    """A stored row outlives the code that wrote it."""
    return status if status in STATUSES else STATUS_OPEN
