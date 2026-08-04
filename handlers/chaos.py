"""Telegram surface for the Chaos Chain daily challenge.

Kept apart from the download handlers on purpose: this module imports
nothing from them and touches neither their database nor their state. The
only shared object is the Pyrogram client itself.

One Telegram constraint shapes the whole design. A Mini App can only send
data back to the bot when it was opened from a *reply keyboard* button, in
a private chat — an inline button or the menu button gives no way home
without a server. So "Играть" is a reply-keyboard button and the game only
works in DMs.
"""
import asyncio
import html
import logging
import os

from pyrogram import filters
from pyrogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from services.chaos.events import APPLES_TO_CLEAR_DAY, MERGE_TARGET
from services.chaos.seed import day_key, shift_day_key
from services.chaos.storage import ChaosStorage
from services.chaos.validate import RunRejected, validate_run

WEBAPP_URL = os.getenv(
    "CHAOS_WEBAPP_URL",
    "https://daring667.github.io/tiktokloaderhub_bot/",
)

LAST_ANNOUNCED_KEY = "last_announced_day"
ANNOUNCE_POLL_SECONDS = 60

# Pyrogram has no built-in filter for this message type.
web_app_data_filter = filters.create(
    lambda _, __, message: getattr(message, "web_app_data", None) is not None
)


def _display_name(user) -> str:
    if not user:
        return "Аноним"
    return user.first_name or user.username or str(user.id)


def _play_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🎮 Играть", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )


def _format_top(rows: list, day: str) -> str:
    if not rows:
        return f"🏆 <b>{day}</b>\n\nСегодня ещё никто не играл. Есть шанс возглавить таблицу."

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 <b>Рейтинг за {day}</b>", ""]
    for i, row in enumerate(rows):
        place = medals[i] if i < len(medals) else f"{i + 1}."
        name = html.escape(row["display_name"] or "Аноним")
        chain = " 🔗" if row.get("chain_completed") else ""
        lines.append(
            f"{place} {name} — <b>{row['score']}</b> · 🍎 {row['apples']}{chain}"
        )
    return "\n".join(lines)


def register(app, db=None, storage: ChaosStorage | None = None):
    """Wires up the challenge. `db` is the downloader's database and is used
    read-only, purely to find out who has opted out of broadcasts."""
    store = storage or ChaosStorage()

    @app.on_message(filters.command("chaos") & filters.private)
    async def chaos_handler(client, message):
        today = day_key()
        streak = store.get_streak(message.from_user.id) if message.from_user else None
        best = store.get_personal_best(message.from_user.id, today) if message.from_user else None

        lines = [
            "🌀 <b>Chaos Chain</b>",
            "",
            "Змейка, в которой каждое съеденное яблоко меняет правила.",
            "Чем больше хаоса накопилось, тем дороже стоит яблоко.",
            f"{APPLES_TO_CLEAR_DAY} 🍎 — день засчитан, и открывается следующее",
            f"звено: «Слияние». Собери плитку {MERGE_TARGET} — пройдёшь цепочку 🔗.",
            "",
            f"День: <b>{today}</b>",
        ]
        if best:
            lines.append(f"Твой результат сегодня: <b>{best['score']}</b> · 🍎 {best['apples']}")
        if streak and streak["current"]:
            lines.append(f"Серия: <b>{streak['current']}</b> дней подряд")

        await message.reply(
            "\n".join(lines),
            reply_markup=_play_keyboard(),
        )

    @app.on_message(filters.command("top") & (filters.private | filters.group))
    async def top_handler(client, message):
        today = day_key()
        await message.reply(_format_top(store.get_daily_top(today), today))

    @app.on_message(filters.command("streak") & filters.private)
    async def streak_handler(client, message):
        if not message.from_user:
            return
        today = day_key()
        state = store.get_streak(message.from_user.id)
        best = store.get_personal_best(message.from_user.id, today)

        lines = [
            "🔥 <b>Твоя серия</b>",
            "",
            f"Сейчас: <b>{state['current']}</b> дней подряд",
            f"Лучшая: <b>{state['best']}</b>",
        ]
        if best:
            lines.append(f"\nСегодня: <b>{best['score']}</b> очков · 🍎 {best['apples']}")
        elif state["last_day_key"] == shift_day_key(today, -1):
            lines.append("\nСегодня ещё не играл — серия оборвётся, если не успеть.")
        await message.reply("\n".join(lines))

    @app.on_message(web_app_data_filter & filters.private)
    async def result_handler(client, message):
        user = message.from_user
        if not user:
            return

        today = day_key()
        submissions = store.count_submissions(user.id, today)

        try:
            run = validate_run(message.web_app_data.data,
                               submissions_today=submissions)
        except RunRejected as exc:
            logging.warning("Chaos run rejected from %s: %s", user.id, exc)
            await message.reply(f"❌ Результат не принят: {html.escape(str(exc))}")
            return

        previous_best = store.get_personal_best(user.id, today)
        store.save_run(user.id, _display_name(user), run)

        lines = [f"Готово: <b>{run['score']}</b> очков · 🍎 {run['apples']}"]

        if run["cleared"]:
            state = store.bump_streak(user.id, today)
            lines.append(f"✅ День засчитан. Серия: <b>{state['current']}</b>")
        else:
            need = APPLES_TO_CLEAR_DAY - run["apples"]
            lines.append(f"До зачёта не хватило {need} 🍎")

        if run.get("chain_completed"):
            lines.append("🔗 <b>Цепочка пройдена целиком.</b>")

        if previous_best and run["score"] > previous_best["score"]:
            lines.append(f"🔝 Личный рекорд дня побит (было {previous_best['score']})")

        top = store.get_daily_top(today)
        place = next((i + 1 for i, row in enumerate(top) if row["user_id"] == user.id), None)
        if place:
            lines.append(f"Место в рейтинге: <b>{place}</b> из {len(top)}")

        await message.reply("\n".join(lines), reply_markup=_play_keyboard())

    return store


async def run_daily_announcer(client, db, store: ChaosStorage, get_now=None):
    """Posts the new challenge when the game day turns over.

    A background task rather than a systemd timer: a timer would need its own
    Telegram credentials. The last announced day is persisted, so a restart
    at 12:05 still sends the post instead of skipping it.
    """
    while True:
        try:
            today = day_key(get_now() if get_now else None)
            seen = store.get_meta(LAST_ANNOUNCED_KEY)
            if seen is None:
                # First ever start. Announcing right now would fire at
                # whatever time the bot happened to be deployed and read as
                # spam; wait for a real rollover instead.
                store.set_meta(LAST_ANNOUNCED_KEY, today)
            elif seen != today:
                await _announce(client, db, store, today)
                store.set_meta(LAST_ANNOUNCED_KEY, today)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Chaos announcer failed; will retry")
        await asyncio.sleep(ANNOUNCE_POLL_SECONDS)


async def _announce(client, db, store: ChaosStorage, today: str) -> None:
    yesterday = shift_day_key(today, -1)
    top = store.get_daily_top(yesterday, limit=1)

    lines = ["🌀 <b>Новый день Chaos Chain</b>", "", f"Сегодняшняя цепочка: <b>{today}</b>"]
    if top:
        champion = html.escape(top[0]["display_name"] or "Аноним")
        lines.append(f"Вчера лучший — {champion} с {top[0]['score']} очками.")
    lines.append("\nНажми /chaos, чтобы играть.")
    text = "\n".join(lines)

    # Reuse the downloader's opt-out list so nobody gets two separate
    # unsubscribe settings to manage.
    user_ids = db.get_broadcast_subscribed_user_ids() if db else []
    for user_id in user_ids:
        try:
            await client.send_message(user_id, text)
        except Exception as exc:
            logging.info("Chaos announcement to %s failed: %s", user_id, exc)
        await asyncio.sleep(0.05)
