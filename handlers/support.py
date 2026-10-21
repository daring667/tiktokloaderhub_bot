"""Support channel: a user reports a problem, the admin answers as the bot.

The reporter never leaves the chat they are already in, and the admin never
has to ask "which link was it?" -- the last failure is attached automatically.

Two rules this module exists to keep:
  * who receives an admin reply is read from the ticket row, never from the
    callback payload, which anyone can replay with an edited id;
  * every admin action checks the sender against ADMIN_ID, because a callback
    button can be pressed by whoever can see the message it is attached to.
"""
import html
import logging

from pyrogram import StopPropagation, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services import support
from services.utils.env import resolve_admin_id

CB = "sup"

ACTION_REPORT = "report"
ACTION_REPLY = "reply"
ACTION_APPEND = "append"

ASK_REPORT = (
    "✍️ Опиши, что случилось — одним сообщением.\n\n"
    "Если проблема была с конкретной ссылкой, я приложу её автоматически."
)


def report_button(label: str = "🆘 Сообщить о проблеме") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"{CB}|new")]])


def _cancel_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Отмена", callback_data=f"{CB}|cancel")]])


def _user_label(user) -> str:
    if user is None:
        return "неизвестно"
    if getattr(user, "username", None):
        return f"@{user.username}"
    name = getattr(user, "first_name", None) or "без имени"
    return f"{name} ({user.id})"


def ticket_card(ticket: dict, who: str) -> str:
    """The admin's view of a ticket."""
    status = support.normalize_status(ticket.get("status"))
    lines = [
        f"🆘 <b>Обращение #{ticket['id']}</b> · {support.status_label(status)}",
        "",
        f"От: {html.escape(who)}",
    ]
    if ticket.get("platform"):
        lines.append(f"Платформа: {html.escape(str(ticket['platform']))}")
    if ticket.get("url"):
        lines.append(f"Ссылка: {html.escape(str(ticket['url']))}")
    if ticket.get("error_type"):
        lines.append(f"Ошибка: <code>{html.escape(str(ticket['error_type']))}</code>")
    lines += ["", "<b>Сообщение:</b>", html.escape(ticket.get("message") or "")]
    return "\n".join(lines)


def ticket_markup(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Ответить", callback_data=f"{CB}|reply|{ticket_id}")],
        [
            InlineKeyboardButton("🔍 Разбираюсь",
                                 callback_data=f"{CB}|st|{ticket_id}|{support.STATUS_INVESTIGATING}"),
            InlineKeyboardButton("✅ Исправлено",
                                 callback_data=f"{CB}|st|{ticket_id}|{support.STATUS_FIXED}"),
        ],
        [InlineKeyboardButton("📁 Закрыть",
                              callback_data=f"{CB}|st|{ticket_id}|{support.STATUS_CLOSED}")],
    ])


def register(app, db):
    admin_id = resolve_admin_id()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_admin(user) -> bool:
        return bool(admin_id) and user is not None and user.id == admin_id

    async def notify_user(client, user_id: int, text: str) -> bool:
        """Best effort: someone may have blocked the bot since reporting."""
        try:
            await client.send_message(user_id, text, parse_mode=ParseMode.HTML)
            return True
        except Exception as e:
            logging.warning("could not deliver support message to %s: %s", user_id, e)
            return False

    async def start_report(reply_to, user_id: int):
        """Ask for the text, offering to extend an open ticket if there is one.

        Remembering a detail five minutes later is the common case, and it
        should continue the conversation rather than open a second ticket the
        admin then has to connect up by hand.
        """
        existing = None
        try:
            existing = db.get_latest_open_ticket(user_id)
        except Exception as e:
            logging.warning("could not look up open tickets: %s", e)

        if existing:
            await reply_to.reply(
                f"У тебя уже открыто обращение <b>#{existing['id']}</b>.\n"
                "Дополнить его или завести новое?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"➕ Дополнить #{existing['id']}",
                        callback_data=f"{CB}|add|{existing['id']}")],
                    [InlineKeyboardButton(
                        "🆕 Новое обращение", callback_data=f"{CB}|fresh")],
                    [InlineKeyboardButton("Отмена", callback_data=f"{CB}|cancel")],
                ]),
                parse_mode=ParseMode.HTML,
            )
            return

        db.set_pending(user_id, ACTION_REPORT)
        await reply_to.reply(ASK_REPORT, reply_markup=_cancel_markup())

    # ------------------------------------------------------------------
    # The pending-input catcher runs ahead of every other handler
    # ------------------------------------------------------------------

    async def _has_pending(_flt, _client, message) -> bool:
        user = getattr(message, "from_user", None)
        if not user or not getattr(message, "text", None):
            return False
        try:
            return db.get_pending(
                user.id, support.PENDING_TTL_MINUTES) is not None
        except Exception:
            return False

    @app.on_message(filters.private & filters.text & filters.create(_has_pending),
                    group=-1)
    async def capture_pending(client, message):
        user = message.from_user
        pending = db.get_pending(user.id, support.PENDING_TTL_MINUTES)
        if not pending:
            return

        text = message.text or ""
        # A command means they moved on; drop the prompt rather than storing
        # "/start" as somebody's bug report.
        if text.startswith("/"):
            db.clear_pending(user.id)
            return

        action = pending.get("action")

        if action == ACTION_REPORT:
            await _finish_report(client, message, user, text)
        elif action == ACTION_APPEND:
            await _finish_append(client, message, user, pending.get("ticket_id"), text)
        elif action == ACTION_REPLY and is_admin(user):
            await _finish_reply(client, message, pending.get("ticket_id"), text)
        else:
            db.clear_pending(user.id)
            return

        raise StopPropagation

    async def _finish_report(client, message, user, text):
        try:
            body = support.validate_report(text)
            support.check_quota(db.count_open_tickets(user.id))
        except support.ReportRejected as e:
            await message.reply(str(e))
            return  # the prompt stays open so they can simply try again

        db.clear_pending(user.id)
        context = db.get_failure_context(user.id) or {}
        ticket_id = db.create_ticket(
            user.id, body,
            platform=context.get("platform"),
            url=context.get("url"),
            error_type=context.get("error_type"),
        )
        db.register_user(user.id, user.username, user.first_name)

        await message.reply(
            f"✅ Обращение <b>#{ticket_id}</b> создано. "
            "Отвечу сюда же, как разберусь.",
            parse_mode=ParseMode.HTML,
        )

        if admin_id:
            ticket = db.get_ticket(ticket_id)
            try:
                await client.send_message(
                    admin_id, ticket_card(ticket, _user_label(user)),
                    reply_markup=ticket_markup(ticket_id),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logging.warning("could not deliver ticket #%s: %s", ticket_id, e)

    async def _finish_append(client, message, user, ticket_id, text):
        ticket = db.get_ticket(ticket_id) if ticket_id else None
        # The pending row is keyed by user, but the ticket it names must still
        # belong to them before anything they type is attached to it.
        if not ticket or ticket["user_id"] != user.id:
            db.clear_pending(user.id)
            await message.reply("Обращение не найдено.")
            return
        try:
            body = support.validate_report(text)
        except support.ReportRejected as e:
            await message.reply(str(e))
            return  # the prompt stays open so they can try again

        db.clear_pending(user.id)
        db.add_reply(ticket_id, "user", body)
        await message.reply(
            f"✅ Добавил к обращению <b>#{ticket_id}</b>.",
            parse_mode=ParseMode.HTML)

        if admin_id:
            try:
                await client.send_message(
                    admin_id,
                    f"➕ <b>Дополнение к #{ticket_id}</b>\n"
                    f"От: {html.escape(_user_label(user))}\n\n"
                    f"{html.escape(body)}",
                    reply_markup=ticket_markup(ticket_id),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logging.warning("could not deliver addition to #%s: %s", ticket_id, e)

    async def _finish_reply(client, message, ticket_id, text):
        db.clear_pending(message.from_user.id)
        ticket = db.get_ticket(ticket_id) if ticket_id else None
        if not ticket:
            await message.reply("Обращение не найдено — возможно, оно удалено.")
            return

        body = (text or "").strip()
        if not body:
            await message.reply("Пустой ответ не отправлен.")
            return

        db.add_reply(ticket_id, "admin", body)
        # The recipient comes from the ticket, never from anything the button
        # carried: a replayed payload must not be able to pick who gets this.
        delivered = await notify_user(
            client, ticket["user_id"],
            f"💬 <b>Ответ по обращению #{ticket_id}</b>\n\n{html.escape(body)}",
        )
        await message.reply(
            f"✅ Ответ отправлен по обращению #{ticket_id}."
            if delivered else
            f"⚠️ Не смог доставить ответ по #{ticket_id} — пользователь "
            "заблокировал бота или не открывал с ним чат."
        )

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app.on_message(filters.command("report") & filters.private)
    async def report_command(client, message):
        if not message.from_user:
            return
        await start_report(message, message.from_user.id)

    @app.on_message(filters.command("tickets") & filters.private)
    async def tickets_command(client, message):
        if not is_admin(message.from_user):
            await message.reply("⛔ Нет доступа.")
            return
        tickets = db.list_tickets(
            statuses=(support.STATUS_OPEN, support.STATUS_INVESTIGATING), limit=10)
        if not tickets:
            await message.reply("Открытых обращений нет.")
            return
        for ticket in tickets:
            names = db.get_user_display_names([ticket["user_id"]])
            who = names.get(ticket["user_id"]) or str(ticket["user_id"])
            await message.reply(
                ticket_card(ticket, str(who)),
                reply_markup=ticket_markup(ticket["id"]),
                parse_mode=ParseMode.HTML,
            )

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    @app.on_callback_query(filters.regex(f"^{CB}\\|"))
    async def on_support_callback(client, callback):
        user = callback.from_user
        if not user:
            await callback.answer()
            return

        parts = callback.data.split("|")
        action = parts[1] if len(parts) > 1 else ""

        if action == "new":
            try:
                await start_report(callback.message, user.id)
            except Exception as e:
                logging.warning("could not start a report: %s", e)
            await callback.answer()
            return

        if action == "fresh":
            db.set_pending(user.id, ACTION_REPORT)
            try:
                await callback.message.edit_text(ASK_REPORT,
                                                 reply_markup=_cancel_markup())
            except Exception:
                pass
            await callback.answer()
            return

        if action == "add" and len(parts) > 2:
            try:
                ticket_id = int(parts[2])
            except ValueError:
                await callback.answer("Неверное обращение.", show_alert=True)
                return
            ticket = db.get_ticket(ticket_id)
            # The button carries an id, so confirm the ticket is theirs before
            # letting what they type be attached to it.
            if not ticket or ticket["user_id"] != user.id:
                await callback.answer("Обращение не найдено.", show_alert=True)
                return
            db.set_pending(user.id, ACTION_APPEND, ticket_id)
            try:
                await callback.message.edit_text(
                    f"✍️ Напиши, что добавить к обращению #{ticket_id}.",
                    reply_markup=_cancel_markup())
            except Exception:
                pass
            await callback.answer()
            return

        if action == "cancel":
            db.clear_pending(user.id)
            try:
                await callback.message.edit_text("Отменено.")
            except Exception:
                pass
            await callback.answer()
            return

        # Everything below belongs to the admin only. A callback button can be
        # pressed by anyone who can see the message carrying it.
        if not is_admin(user):
            await callback.answer("⛔ Нет доступа.", show_alert=True)
            return

        if action == "reply" and len(parts) > 2:
            try:
                ticket_id = int(parts[2])
            except ValueError:
                await callback.answer("Неверное обращение.", show_alert=True)
                return
            if not db.get_ticket(ticket_id):
                await callback.answer("Обращение не найдено.", show_alert=True)
                return
            db.set_pending(user.id, ACTION_REPLY, ticket_id)
            await callback.message.reply(
                f"✍️ Напиши ответ по обращению #{ticket_id} одним сообщением.",
                reply_markup=_cancel_markup(),
            )
            await callback.answer()
            return

        if action == "st" and len(parts) > 3:
            try:
                ticket_id = int(parts[2])
            except ValueError:
                await callback.answer("Неверное обращение.", show_alert=True)
                return
            status = support.normalize_status(parts[3])
            if status != parts[3]:
                await callback.answer("Неизвестный статус.", show_alert=True)
                return
            ticket = db.get_ticket(ticket_id)
            if not ticket:
                await callback.answer("Обращение не найдено.", show_alert=True)
                return

            db.set_ticket_status(ticket_id, status)
            notice = support.status_notice(status)
            if notice:
                await notify_user(
                    client, ticket["user_id"],
                    f"<b>Обращение #{ticket_id}</b>\n{html.escape(notice)}")

            refreshed = db.get_ticket(ticket_id)
            names = db.get_user_display_names([ticket["user_id"]])
            who = names.get(ticket["user_id"]) or str(ticket["user_id"])
            try:
                await callback.message.edit_text(
                    ticket_card(refreshed, str(who)),
                    reply_markup=ticket_markup(ticket_id),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                if "MESSAGE_NOT_MODIFIED" not in str(e).upper():
                    logging.warning("ticket card refresh failed: %s", e)
            await callback.answer(support.status_label(status))
            return

        await callback.answer()
