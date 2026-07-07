"""Telegram bot — commands for creating, listing, and deleting alerts."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from alert_bot import db
from alert_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, VALID_EXCHANGES

logger = logging.getLogger("conflux.telegram")

# Exchange subscribe queues — set by main.py before bot starts
_exchange_queues: dict[str, asyncio.Queue] = {}
_db_conn = None


def init_telegram(db_conn, exchange_queues: dict[str, asyncio.Queue]) -> None:
    """Set shared state for the Telegram handlers."""
    global _db_conn, _exchange_queues
    _db_conn = db_conn
    _exchange_queues = exchange_queues


# ── Command Handlers ─────────────────────────────────────────────────


async def cmd_newalert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/newalert <symbol> <exchange> <target_price> <range_pct> <note...>"""
    if not context.args or len(context.args) < 4:
        await update.message.reply_text(
            "Usage: /newalert <symbol> <exchange> <target_price> <range_pct> [note...]\n"
            "Example: /newalert BTCUSDT binance 65000 2 resistance retest"
        )
        return

    symbol = context.args[0].upper()
    exchange = context.args[1].lower()
    target_price_str = context.args[2]
    range_pct_str = context.args[3]
    note = " ".join(context.args[4:]) if len(context.args) > 4 else None

    # Validate exchange
    if exchange not in VALID_EXCHANGES:
        await update.message.reply_text(
            f"❌ Invalid exchange: '{exchange}'\n"
            f"Valid exchanges: {', '.join(sorted(VALID_EXCHANGES))}"
        )
        return

    # Validate target_price
    try:
        target_price = float(target_price_str)
    except ValueError:
        await update.message.reply_text(
            f"❌ Invalid target_price: '{target_price_str}' — must be a number"
        )
        return

    # Validate range_pct
    try:
        range_pct = float(range_pct_str)
    except ValueError:
        await update.message.reply_text(
            f"❌ Invalid range_pct: '{range_pct_str}' — must be a number"
        )
        return

    # Create alert
    alert_id = db.create_alert(_db_conn, symbol, exchange, target_price, range_pct, note)

    # Echo back all parsed values so the user catches typos
    note_display = f'note="{note}"' if note else "no note"
    await update.message.reply_text(
        f"✅ Alert #{alert_id} created\n"
        f"  symbol={symbol}\n"
        f"  exchange={exchange}\n"
        f"  target={target_price}\n"
        f"  range={range_pct}%\n"
        f"  {note_display}"
    )

    # Push dynamic subscribe request to the exchange task
    if exchange in _exchange_queues:
        await _exchange_queues[exchange].put(("subscribe", symbol))
        logger.info("Queued subscribe for %s on %s", symbol, exchange)


async def cmd_listalerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/listalerts — show all alerts regardless of status."""
    alerts = db.list_alerts(_db_conn)

    if not alerts:
        await update.message.reply_text("No alerts found.")
        return

    lines = []
    keyboard = []
    for a in alerts:
        note_str = f' note="{a["note"]}"' if a["note"] else ""
        lines.append(
            f'#{a["id"]} {a["symbol"]} {a["exchange"]} '
            f'target={a["target_price"]} range={a["range_pct"]}%'
            f'{note_str} [{a["status"]}]'
        )
        # Add a button for this alert
        keyboard.append([InlineKeyboardButton(f"❌ Delete #{a['id']}", callback_data=f"del_{a['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("\n".join(lines), reply_markup=reply_markup)

async def btn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button taps."""
    query = update.callback_query
    await query.answer()  # Acknowledge the tap

    if query.data.startswith("del_"):
        try:
            alert_id = int(query.data.split("_")[1])
            deleted = db.delete_alert(_db_conn, alert_id)
            if deleted:
                await query.message.reply_text(f"✅ Alert #{alert_id} deleted via button.")
            else:
                await query.message.reply_text(f"❌ No alert with ID #{alert_id}.")
        except ValueError:
            pass


async def cmd_deletealert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deletealert <id> — delete an alert by its ID."""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /deletealert <id>")
        return

    try:
        alert_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            f"❌ Invalid ID: '{context.args[0]}' — must be an integer"
        )
        return

    deleted = db.delete_alert(_db_conn, alert_id)
    if deleted:
        await update.message.reply_text(f"✅ Alert #{alert_id} deleted.")
    else:
        await update.message.reply_text(f"❌ No alert with ID #{alert_id}.")


# ── Alert Notification ───────────────────────────────────────────────

_bot_app: Application | None = None


async def send_telegram_alert(alert, price: float) -> None:
    """Send a trigger notification to the configured Telegram chat."""
    if _bot_app is None:
        logger.error("Bot app not initialized, cannot send alert")
        return

    note_str = f'\n📝 {alert["note"]}' if alert["note"] else ""
    message = (
        f'🚨 Alert #{alert["id"]} TRIGGERED\n'
        f'  {alert["symbol"]} on {alert["exchange"]}\n'
        f'  Price: {price}\n'
        f'  Target: {alert["target_price"]} ± {alert["range_pct"]}%'
        f'{note_str}'
    )

    await _bot_app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    logger.info("Sent Telegram alert for #%d", alert["id"])


# ── Bot Setup ────────────────────────────────────────────────────────


def build_application() -> Application:
    """Build and return the Telegram bot Application (polling mode)."""
    global _bot_app
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("newalert", cmd_newalert))
    app.add_handler(CommandHandler("listalerts", cmd_listalerts))
    app.add_handler(CommandHandler("deletealert", cmd_deletealert))
    app.add_handler(CallbackQueryHandler(btn_callback))

    _bot_app = app
    return app
