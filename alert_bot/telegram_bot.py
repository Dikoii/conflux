"""Telegram bot — commands for creating, listing, and deleting alerts and trades."""

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

# ── Alert Conversation states ─────────────────────────────────────────
A_SYMBOL, A_EXCHANGE, A_PRICE, A_RANGE, A_NOTE = range(5)

# ── Trade Conversation states ─────────────────────────────────────────
T_SYMBOL, T_EXCHANGE, T_SIDE, T_ENTRY, T_SL, T_TP = range(10, 16)


def init_telegram(db_conn, exchange_queues: dict[str, asyncio.Queue]) -> None:
    """Set shared state for the Telegram handlers."""
    global _db_conn, _exchange_queues
    _db_conn = db_conn
    _exchange_queues = exchange_queues


# ── /newalert — Guided Conversation ──────────────────────────────────

async def conv_alert_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "🔔 *New Alert — Step 1/5*\n\nWhat is the trading symbol?\n_(e.g. BTCUSDT)_",
        parse_mode="MarkdownV2",
    )
    return A_SYMBOL

async def conv_alert_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    return A_EXCHANGE

async def conv_alert_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["exchange"] = query.data.split("_")[1]
    await query.message.reply_text(
        f"✅ Exchange: *{context.user_data['exchange'].capitalize()}*\n\n💰 *Step 3/5* — What is the target price?",
        parse_mode="Markdown",
    )
    return A_PRICE

async def conv_alert_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["target_price"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return A_PRICE

    await update.message.reply_text(
        f"✅ Target: *{context.user_data['target_price']}*\n\n📏 *Step 4/5* — What range percentage?",
        parse_mode="Markdown",
    )
    return A_RANGE

async def conv_alert_range(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["range_pct"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return A_RANGE

    keyboard = [[InlineKeyboardButton("⏭ Skip", callback_data="note_skip")]]
    await update.message.reply_text(
        f"✅ Range: *{context.user_data['range_pct']}%*\n\n📝 *Step 5/5* — Any note? (or tap Skip)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return A_NOTE

async def conv_alert_note_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["note"] = update.message.text.strip()
    return await _create_alert(update.message, context)

async def conv_alert_note_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["note"] = None
    return await _create_alert(query.message, context)

async def _create_alert(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    d = context.user_data
    alert_id = db.create_alert(
        _db_conn, d["symbol"], d["exchange"], d["target_price"], d["range_pct"], d.get("note")
    )
    note_display = f'\n  📝 {d["note"]}' if d.get("note") else ""
    await message.reply_text(
        f"✅ *Alert #{alert_id} created!*\n"
        f"  📈 {d['symbol']} on {d['exchange'].capitalize()}\n"
        f"  🎯 Target: `{d['target_price']}` ±`{d['range_pct']}%`{note_display}",
        parse_mode="Markdown",
    )
    if d["exchange"] in _exchange_queues:
        await _exchange_queues[d["exchange"]].put(("subscribe", d["symbol"]))
    context.user_data.clear()
    return ConversationHandler.END


# ── /newtrade — Guided Conversation ──────────────────────────────────

async def conv_trade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "📊 *New Trade Tracker — Step 1/6*\n\nWhat is the trading symbol?\n_(e.g. BTCUSDT)_",
        parse_mode="Markdown",
    )
    return T_SYMBOL

async def conv_trade_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["symbol"] = update.message.text.strip().upper()
    keyboard = [[
        InlineKeyboardButton("Binance", callback_data="ex_binance"),
        InlineKeyboardButton("Bitget", callback_data="ex_bitget"),
        InlineKeyboardButton("OKX", callback_data="ex_okx"),
    ]]
    await update.message.reply_text(
        f"✅ Symbol: *{context.user_data['symbol']}*\n\n📡 *Step 2/6* — Which exchange?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return T_EXCHANGE

async def conv_trade_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["exchange"] = query.data.split("_")[1]
    keyboard = [[
        InlineKeyboardButton("🟢 LONG", callback_data="side_long"),
        InlineKeyboardButton("🔴 SHORT", callback_data="side_short"),
    ]]
    await query.message.reply_text(
        f"✅ Exchange: *{context.user_data['exchange'].capitalize()}*\n\n📈 *Step 3/6* — Long or Short?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return T_SIDE

async def conv_trade_side(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["side"] = query.data.split("_")[1]
    side_emoji = "🟢 LONG" if context.user_data["side"] == "long" else "🔴 SHORT"
    await query.message.reply_text(
        f"✅ Side: *{side_emoji}*\n\n🚪 *Step 4/6* — Entry price?",
        parse_mode="Markdown",
    )
    return T_ENTRY

async def conv_trade_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["entry"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return T_ENTRY
    await update.message.reply_text(
        f"✅ Entry: *{context.user_data['entry']}*\n\n🛑 *Step 5/6* — Stop Loss (SL) price?",
        parse_mode="Markdown",
    )
    return T_SL

async def conv_trade_sl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["sl"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return T_SL
    await update.message.reply_text(
        f"✅ Stop Loss: *{context.user_data['sl']}*\n\n🎯 *Step 6/6* — Take Profit (TP) price?",
        parse_mode="Markdown",
    )
    return T_TP

async def conv_trade_tp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["tp"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return T_TP
        
    d = context.user_data
    trade_id = db.create_trade(
        _db_conn, d["symbol"], d["exchange"], d["side"], d["entry"], d["sl"], d["tp"]
    )
    
    # Calculate RR
    risk = abs(d["entry"] - d["sl"])
    reward = abs(d["tp"] - d["entry"])
    rr_str = f"1:{reward/risk:.2f}" if risk > 0 else "N/A"
    
    emoji = "🟢" if d["side"] == "long" else "🔴"
    await update.message.reply_text(
        f"✅ *Trade Tracker #{trade_id} created!*\n\n"
        f"  {emoji} *{d['side'].upper()} {d['symbol']}* ({d['exchange'].capitalize()})\n"
        f"  🚪 Entry: `{d['entry']}`\n"
        f"  🛑 SL: `{d['sl']}`\n"
        f"  🎯 TP: `{d['tp']}`\n"
        f"  ⚖️ RR: `{rr_str}`",
        parse_mode="Markdown",
    )
    
    # Push subscribe request so we get live price updates for tracking
    if d["exchange"] in _exchange_queues:
        await _exchange_queues[d["exchange"]].put(("subscribe", d["symbol"]))
        
    context.user_data.clear()
    return ConversationHandler.END


async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


# ── Lists ─────────────────────────────────────────────────────────────

async def cmd_listalerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    all_alerts = db.list_alerts(_db_conn)
    active = [a for a in all_alerts if a["status"] == "active"]
    triggered_count = len(all_alerts) - len(active)

    if not active:
        suffix = f"\n\n_{triggered_count} triggered alert(s) hidden._" if triggered_count else ""
        await update.message.reply_text(f"No active alerts found.{suffix}", parse_mode="Markdown")
        return

    lines = []
    for a in active:
        note_str = f'\n    📝 {a["note"]}' if a["note"] else ""
        lines.append(
            f'#{a["id"]} *{a["symbol"]}* `{a["exchange"]}`  '
            f'target=`{a["target_price"]}` range=`{a["range_pct"]}%`{note_str}'
        )

    buttons = [InlineKeyboardButton(f"❌ #{a['id']}", callback_data=f"dela_{a['id']}") for a in active]
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]

    footer = f"\n\n_{triggered_count} triggered alert(s) hidden._" if triggered_count else ""
    await update.message.reply_text(
        "\n\n".join(lines) + footer, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cmd_listtrades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trades = db.list_open_trades(_db_conn)
    if not trades:
        await update.message.reply_text("No open trades being tracked.")
        return

    lines = []
    for t in trades:
        price = db.get_latest_price(_db_conn, t["exchange"], t["symbol"])
        
        # Calc live PnL and RR
        risk = abs(t["entry_price"] - t["stop_loss"])
        reward = abs(t["take_profit"] - t["entry_price"])
        rr_str = f"1:{reward/risk:.2f}" if risk > 0 else "N/A"
        
        pnl_str = "Waiting for price tick..."
        if price is not None:
            if t["side"] == "long":
                pnl_pct = (price - t["entry_price"]) / t["entry_price"] * 100
            else:
                pnl_pct = (t["entry_price"] - price) / t["entry_price"] * 100
                
            sign = "+" if pnl_pct > 0 else ""
            pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
            pnl_str = f"Live PnL: *{sign}{pnl_pct:.2f}%* {pnl_emoji}"
            price_str = str(price)
        else:
            price_str = "?"
            
        emoji = "🟢" if t["side"] == "long" else "🔴"
        
        lines.append(
            f"#{t['id']} {emoji} *{t['symbol']}* ({t['exchange']})\n"
            f"Entry: `{t['entry_price']}` | Current: `{price_str}`\n"
            f"SL: `{t['stop_loss']}` | TP: `{t['take_profit']}`\n"
            f"RR: `{rr_str}`\n"
            f"{pnl_str}"
        )

    # 2-column buttons to delete (cancel tracking)
    buttons = [InlineKeyboardButton(f"❌ #{t['id']}", callback_data=f"delt_{t['id']}") for t in trades]
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]

    await update.message.reply_text(
        "\n\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ── Inline button callbacks ───────────────────────────────────────────

async def btn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data.startswith("dela_"): # Delete alert
        try:
            alert_id = int(query.data.split("_")[1])
            if db.delete_alert(_db_conn, alert_id):
                await query.message.reply_text(f"✅ Alert #{alert_id} deleted.")
        except ValueError:
            pass
    elif query.data.startswith("delt_"): # Delete trade
        try:
            trade_id = int(query.data.split("_")[1])
            # Just cancel tracking, we can use a hard delete or mark status='cancelled'. We'll hard delete.
            _db_conn.execute("DELETE FROM trades WHERE id=?", (trade_id,))
            _db_conn.commit()
            await query.message.reply_text(f"✅ Trade Tracking #{trade_id} cancelled.")
        except ValueError:
            pass


# ── Alert/Trade Notification ──────────────────────────────────────────

_bot_app: Application | None = None

async def send_telegram_alert(alert, price: float) -> None:
    if _bot_app is None: return
    note_str = f'\n📝 {alert["note"]}' if alert["note"] else ""
    message = (
        f'🚨 *Alert #{alert["id"]} TRIGGERED*\n'
        f'  📈 {alert["symbol"]} on {alert["exchange"]}\n'
        f'  💰 Price: `{price}`\n'
        f'  🎯 Target: `{alert["target_price"]}` ±`{alert["range_pct"]}%`{note_str}'
    )
    await _bot_app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")

async def send_telegram_trade_close(trade, price: float, pnl_pct: float, is_tp: bool) -> None:
    """Send notification when a trade hits SL or TP."""
    if _bot_app is None: return
    
    emoji = "🟢" if is_tp else "🔴"
    reason = "TAKE PROFIT (TP)" if is_tp else "STOP LOSS (SL)"
    sign = "+" if pnl_pct > 0 else ""
    
    message = (
        f'{emoji} *TRADE #{trade["id"]} AUTO-CLOSED*\n\n'
        f'  *Hit {reason}*\n'
        f'  {trade["side"].upper()} {trade["symbol"]} on {trade["exchange"]}\n'
        f'  Closed Price: `{price}`\n'
        f'  Final PnL: *{sign}{pnl_pct:.2f}%*'
    )
    await _bot_app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")


# ── Bot Setup ─────────────────────────────────────────────────────────

def build_application() -> Application:
    global _bot_app
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    newalert_conv = ConversationHandler(
        entry_points=[CommandHandler("newalert", conv_alert_start)],
        states={
            A_SYMBOL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_alert_symbol)],
            A_EXCHANGE: [CallbackQueryHandler(conv_alert_exchange, pattern="^ex_")],
            A_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_alert_price)],
            A_RANGE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_alert_range)],
            A_NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, conv_alert_note_text),
                CallbackQueryHandler(conv_alert_note_skip, pattern="^note_skip$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", conv_cancel)],
    )

    newtrade_conv = ConversationHandler(
        entry_points=[CommandHandler("newtrade", conv_trade_start)],
        states={
            T_SYMBOL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_trade_symbol)],
            T_EXCHANGE: [CallbackQueryHandler(conv_trade_exchange, pattern="^ex_")],
            T_SIDE:     [CallbackQueryHandler(conv_trade_side, pattern="^side_")],
            T_ENTRY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_trade_entry)],
            T_SL:       [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_trade_sl)],
            T_TP:       [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_trade_tp)],
        },
        fallbacks=[CommandHandler("cancel", conv_cancel)],
    )

    app.add_handler(newalert_conv)
    app.add_handler(newtrade_conv)
    app.add_handler(CommandHandler("listalerts", cmd_listalerts))
    app.add_handler(CommandHandler("listtrades", cmd_listtrades))
    app.add_handler(CallbackQueryHandler(btn_callback))

    _bot_app = app
    return app
