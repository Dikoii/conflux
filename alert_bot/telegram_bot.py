"""Telegram bot — commands for creating, listing, and deleting alerts."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from alert_bot import db
from alert_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, VALID_EXCHANGES

logger = logging.getLogger("conflux.telegram")

# Exchange subscribe queues — set by main.py before bot starts
_exchange_queues: dict[str, asyncio.Queue] = {}
_db_conn = None

# ── Conversation states ───────────────────────────────────────────────
SYMBOL, EXCHANGE, PRICE, RANGE, NOTE = range(5)


def init_telegram(db_conn, exchange_queues: dict[str, asyncio.Queue]) -> None:
    """Set shared state for the Telegram handlers."""
    global _db_conn, _exchange_queues
    _db_conn = db_conn
    _exchange_queues = exchange_queues


# ── /newalert — Guided Conversation ──────────────────────────────────

async def conv_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/newalert entry point — ask for symbol."""
    context.user_data.clear()
    await update.message.reply_text(
        "🔔 *New Alert — Step 1/5*\n\nWhat is the trading symbol?\n_(e.g. BTCUSDT for Binance/Bitget, BTC\\-USDT for OKX)_",
        parse_mode="MarkdownV2",
    )
    return SYMBOL


async def conv_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive symbol, ask for exchange."""
    context.user_data["symbol"] = update.message.text.strip().upper()
    keyboard = [[
        InlineKeyboardButton("Binance", callback_data="ex_binance"),
        InlineKeyboardButton("Bitget", callback_data="ex_bitget"),
        InlineKeyboardButton("OKX", callback_data="ex_okx"),
    ]]
    await update.message.reply_text(
        f"✅ Symbol: *{context.user_data['symbol']}*\n\n📡 *Step 2/5* — Which exchange?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return EXCHANGE


async def conv_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive exchange button tap, ask for target price."""
    query = update.callback_query
    await query.answer()
    context.user_data["exchange"] = query.data.split("_")[1]  # e.g. "binance"
    await query.message.reply_text(
        f"✅ Exchange: *{context.user_data['exchange'].capitalize()}*\n\n💰 *Step 3/5* — What is the target price?\n_(e.g. 65000)_",
        parse_mode="Markdown",
    )
    return PRICE


async def conv_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive target price, ask for range %."""
    text = update.message.text.strip()
    try:
        context.user_data["target_price"] = float(text)
    except ValueError:
        await update.message.reply_text("❌ That doesn't look like a number. Please enter a valid price (e.g. 65000):")
        return PRICE

    await update.message.reply_text(
        f"✅ Target: *{context.user_data['target_price']}*\n\n📏 *Step 4/5* — What range percentage?\n_(e.g. 2 means the alert fires when price is within ±2% of your target)_",
        parse_mode="Markdown",
    )
    return RANGE


async def conv_range(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive range %, ask for note."""
    text = update.message.text.strip()
    try:
        context.user_data["range_pct"] = float(text)
    except ValueError:
        await update.message.reply_text("❌ That doesn't look like a number. Please enter a valid percentage (e.g. 2):")
        return RANGE

    keyboard = [[InlineKeyboardButton("⏭ Skip", callback_data="note_skip")]]
    await update.message.reply_text(
        f"✅ Range: *{context.user_data['range_pct']}%*\n\n📝 *Step 5/5* — Any note for this alert?\n_(e.g. 'resistance retest', or tap Skip)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return NOTE


async def conv_note_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive note text and create the alert."""
    context.user_data["note"] = update.message.text.strip()
    return await _create_alert(update.message, context)


async def conv_note_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skip note and create the alert."""
    query = update.callback_query
    await query.answer()
    context.user_data["note"] = None
    return await _create_alert(query.message, context)


async def _create_alert(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Final step: save alert to DB and notify the exchange."""
    d = context.user_data
    alert_id = db.create_alert(
        _db_conn,
        d["symbol"],
        d["exchange"],
        d["target_price"],
        d["range_pct"],
        d.get("note"),
    )
    note_display = f'📝 {d["note"]}' if d.get("note") else "No note"
    await message.reply_text(
        f"✅ *Alert #{alert_id} created!*\n\n"
        f"  📈 Symbol: `{d['symbol']}`\n"
        f"  📡 Exchange: `{d['exchange'].capitalize()}`\n"
        f"  💰 Target: `{d['target_price']}`\n"
        f"  📏 Range: `±{d['range_pct']}%`\n"
        f"  {note_display}",
        parse_mode="Markdown",
    )
    # Push subscribe request
    if d["exchange"] in _exchange_queues:
        await _exchange_queues[d["exchange"]].put(("subscribe", d["symbol"]))
        logger.info("Queued subscribe for %s on %s", d["symbol"], d["exchange"])

    context.user_data.clear()
    return ConversationHandler.END


async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    context.user_data.clear()
    await update.message.reply_text("❌ Alert creation cancelled.")
    return ConversationHandler.END


# ── /listalerts ───────────────────────────────────────────────────────

async def cmd_listalerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/listalerts — show only active alerts with 2-column delete buttons."""
    all_alerts = db.list_alerts(_db_conn)
    active = [a for a in all_alerts if a["status"] == "active"]
    triggered_count = len(all_alerts) - len(active)

    if not active:
        suffix = f"\n\n_{triggered_count} triggered alert(s) are hidden._" if triggered_count else ""
        await update.message.reply_text(f"No active alerts found.{suffix}", parse_mode="Markdown")
        return

    lines = []
    for a in active:
        note_str = f'\n    📝 {a["note"]}' if a["note"] else ""
        lines.append(
            f'#{a["id"]} *{a["symbol"]}* `{a["exchange"]}`  '
            f'target=`{a["target_price"]}` range=`{a["range_pct"]}%`'
            f'{note_str}'
        )

    # Build 2-column button rows
    buttons = [InlineKeyboardButton(f"❌ #{a['id']}", callback_data=f"del_{a['id']}") for a in active]
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]

    footer = f"\n\n_{triggered_count} triggered alert(s) hidden._" if triggered_count else ""
    await update.message.reply_text(
        "\n\n".join(lines) + footer,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Inline button callbacks ───────────────────────────────────────────

async def btn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button taps (delete and exchange selection)."""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("del_"):
        try:
            alert_id = int(query.data.split("_")[1])
            deleted = db.delete_alert(_db_conn, alert_id)
            if deleted:
                await query.message.reply_text(f"✅ Alert #{alert_id} deleted.")
            else:
                await query.message.reply_text(f"❌ No alert with ID #{alert_id}.")
        except ValueError:
            pass


# ── /deletealert (manual fallback) ───────────────────────────────────

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


# ── Alert Notification ────────────────────────────────────────────────

_bot_app: Application | None = None


async def send_telegram_alert(alert, price: float) -> None:
    """Send a trigger notification to the configured Telegram chat."""
    if _bot_app is None:
        logger.error("Bot app not initialized, cannot send alert")
        return

    note_str = f'\n📝 {alert["note"]}' if alert["note"] else ""
    message = (
        f'🚨 *Alert #{alert["id"]} TRIGGERED*\n'
        f'  📈 {alert["symbol"]} on {alert["exchange"]}\n'
        f'  💰 Price: `{price}`\n'
        f'  🎯 Target: `{alert["target_price"]}` ±`{alert["range_pct"]}%`'
        f'{note_str}'
    )

    await _bot_app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")
    logger.info("Sent Telegram alert for #%d", alert["id"])


# ── Bot Setup ─────────────────────────────────────────────────────────


def build_application() -> Application:
    """Build and return the Telegram bot Application (polling mode)."""
    global _bot_app
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Guided new-alert conversation
    newalert_conv = ConversationHandler(
        entry_points=[CommandHandler("newalert", conv_start)],
        states={
            SYMBOL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_symbol)],
            EXCHANGE: [CallbackQueryHandler(conv_exchange, pattern="^ex_")],
            PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_price)],
            RANGE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_range)],
            NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, conv_note_text),
                CallbackQueryHandler(conv_note_skip, pattern="^note_skip$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", conv_cancel)],
    )

    app.add_handler(newalert_conv)
    app.add_handler(CommandHandler("listalerts", cmd_listalerts))
    app.add_handler(CommandHandler("deletealert", cmd_deletealert))
    app.add_handler(CallbackQueryHandler(btn_callback))

    _bot_app = app
    return app
