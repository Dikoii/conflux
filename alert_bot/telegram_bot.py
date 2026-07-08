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

_exchange_queues: dict[str, asyncio.Queue] = {}
_db_conn = None

# ── States ────────────────────────────────────────────────────────────
A_SYMBOL, A_EXCHANGE, A_PRICE, A_RANGE, A_NOTE = range(5)
T_SYMBOL, T_EXCHANGE, T_SIDE, T_ENTRY, T_SL, T_TP = range(10, 16)
U_SL, U_TP = range(20, 22)
C_PRICE = 30


def init_telegram(db_conn, exchange_queues: dict[str, asyncio.Queue]) -> None:
    global _db_conn, _exchange_queues
    _db_conn = db_conn
    _exchange_queues = exchange_queues


# ── /newalert ─────────────────────────────────────────────────────────

async def conv_alert_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("🔔 *New Alert — Step 1/5*\nWhat is the trading symbol?", parse_mode="Markdown")
    return A_SYMBOL

async def conv_alert_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["symbol"] = update.message.text.strip().upper()
    keyboard = [[
        InlineKeyboardButton("Binance", callback_data="ex_binance"),
        InlineKeyboardButton("Bitget", callback_data="ex_bitget"),
        InlineKeyboardButton("OKX", callback_data="ex_okx"),
    ]]
    await update.message.reply_text(f"✅ Symbol: *{context.user_data['symbol']}*\n\n📡 *Step 2/5* — Which exchange?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return A_EXCHANGE

async def conv_alert_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["exchange"] = query.data.split("_")[1]
    await query.message.reply_text(f"✅ Exchange: *{context.user_data['exchange'].capitalize()}*\n\n💰 *Step 3/5* — Target price?", parse_mode="Markdown")
    return A_PRICE

async def conv_alert_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["target_price"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return A_PRICE
    await update.message.reply_text(f"✅ Target: *{context.user_data['target_price']}*\n\n📏 *Step 4/5* — Range percentage?", parse_mode="Markdown")
    return A_RANGE

async def conv_alert_range(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["range_pct"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return A_RANGE
    keyboard = [[InlineKeyboardButton("⏭ Skip", callback_data="note_skip")]]
    await update.message.reply_text(f"✅ Range: *{context.user_data['range_pct']}%*\n\n📝 *Step 5/5* — Any note? (or tap Skip)", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
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
    alert_id = db.create_alert(_db_conn, d["symbol"], d["exchange"], d["target_price"], d["range_pct"], d.get("note"))
    note_display = f'\n  📝 {d["note"]}' if d.get("note") else ""
    await message.reply_text(
        f"✅ *Alert #{alert_id} created!*\n  📈 {d['symbol']} on {d['exchange'].capitalize()}\n  🎯 Target: `{d['target_price']}` ±`{d['range_pct']}%`{note_display}",
        parse_mode="Markdown"
    )
    if d["exchange"] in _exchange_queues:
        await _exchange_queues[d["exchange"]].put(("subscribe", d["symbol"]))
    context.user_data.clear()
    return ConversationHandler.END


# ── /newtrade ─────────────────────────────────────────────────────────

async def conv_trade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("📊 *New Trade Tracker — Step 1/6*\nWhat is the trading symbol?", parse_mode="Markdown")
    return T_SYMBOL

async def conv_trade_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["symbol"] = update.message.text.strip().upper()
    keyboard = [[
        InlineKeyboardButton("Binance", callback_data="ex_binance"),
        InlineKeyboardButton("Bitget", callback_data="ex_bitget"),
        InlineKeyboardButton("OKX", callback_data="ex_okx"),
    ]]
    await update.message.reply_text(f"✅ Symbol: *{context.user_data['symbol']}*\n\n📡 *Step 2/6* — Which exchange?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return T_EXCHANGE

async def conv_trade_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["exchange"] = query.data.split("_")[1]
    keyboard = [[InlineKeyboardButton("🟢 LONG", callback_data="side_long"), InlineKeyboardButton("🔴 SHORT", callback_data="side_short")]]
    await query.message.reply_text(f"✅ Exchange: *{context.user_data['exchange'].capitalize()}*\n\n📈 *Step 3/6* — Long or Short?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return T_SIDE

async def conv_trade_side(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["side"] = query.data.split("_")[1]
    side_emoji = "🟢 LONG" if context.user_data["side"] == "long" else "🔴 SHORT"
    await query.message.reply_text(f"✅ Side: *{side_emoji}*\n\n🚪 *Step 4/6* — Entry price?", parse_mode="Markdown")
    return T_ENTRY

async def conv_trade_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["entry"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return T_ENTRY
    await update.message.reply_text(f"✅ Entry: *{context.user_data['entry']}*\n\n🛑 *Step 5/6* — Stop Loss (SL) price?", parse_mode="Markdown")
    return T_SL

async def conv_trade_sl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["sl"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return T_SL
    await update.message.reply_text(f"✅ Stop Loss: *{context.user_data['sl']}*\n\n🎯 *Step 6/6* — Take Profit (TP) price?", parse_mode="Markdown")
    return T_TP

async def conv_trade_tp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["tp"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return T_TP
        
    d = context.user_data
    trade_id = db.create_trade(_db_conn, d["symbol"], d["exchange"], d["side"], d["entry"], d["sl"], d["tp"])
    
    risk = abs(d["entry"] - d["sl"])
    reward = abs(d["tp"] - d["entry"])
    rr_str = f"1:{reward/risk:.2f}" if risk > 0 else "N/A"
    emoji = "🟢" if d["side"] == "long" else "🔴"
    
    await update.message.reply_text(
        f"✅ *Trade Tracking #{trade_id} started!*\n\n"
        f"  {emoji} *{d['side'].upper()} {d['symbol']}* ({d['exchange'].capitalize()})\n"
        f"  🚪 Entry: `{d['entry']}`\n"
        f"  🛑 SL: `{d['sl']}`\n"
        f"  🎯 TP: `{d['tp']}`\n"
        f"  ⚖️ RR: `{rr_str}`",
        parse_mode="Markdown"
    )
    if d["exchange"] in _exchange_queues:
        await _exchange_queues[d["exchange"]].put(("subscribe", d["symbol"]))
    context.user_data.clear()
    return ConversationHandler.END


# ── /updatetrade ──────────────────────────────────────────────────────

async def conv_updatetrade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: `/updatetrade <id>`", parse_mode="Markdown")
        return ConversationHandler.END

    try:
        trade_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID must be a number.")
        return ConversationHandler.END

    trades = db.list_open_trades(_db_conn)
    trade = next((t for t in trades if t["id"] == trade_id), None)
    if not trade:
        await update.message.reply_text(f"❌ No open trade found with ID #{trade_id}.")
        return ConversationHandler.END

    context.user_data["trade"] = dict(trade)
    keyboard = [[InlineKeyboardButton("⏭ Skip (Keep current SL)", callback_data="skip_sl")]]
    await update.message.reply_text(
        f"🔄 *Update Trade #{trade_id}*\nCurrent SL: `{trade['stop_loss']}`\n\nWhat is your **NEW Stop Loss**? (or tap skip)",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return U_SL

async def conv_updatetrade_sl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["new_sl"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return U_SL
    
    trade = context.user_data["trade"]
    keyboard = [[InlineKeyboardButton("⏭ Skip (Keep current TP)", callback_data="skip_tp")]]
    await update.message.reply_text(
        f"✅ SL set to: `{context.user_data['new_sl']}`\nCurrent TP: `{trade['take_profit']}`\n\nWhat is your **NEW Take Profit**? (or tap skip)",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return U_TP

async def conv_updatetrade_sl_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    trade = context.user_data["trade"]
    context.user_data["new_sl"] = trade["stop_loss"]
    keyboard = [[InlineKeyboardButton("⏭ Skip (Keep current TP)", callback_data="skip_tp")]]
    await query.message.reply_text(
        f"⏭ Kept SL: `{trade['stop_loss']}`\nCurrent TP: `{trade['take_profit']}`\n\nWhat is your **NEW Take Profit**? (or tap skip)",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return U_TP

async def conv_updatetrade_tp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["new_tp"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return U_TP
    return await _commit_update(update.message, context)

async def conv_updatetrade_tp_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["new_tp"] = context.user_data["trade"]["take_profit"]
    return await _commit_update(query.message, context)

async def _commit_update(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    trade = context.user_data["trade"]
    new_sl = context.user_data["new_sl"]
    new_tp = context.user_data["new_tp"]
    
    db.update_trade_sl_tp(_db_conn, trade["id"], new_sl, new_tp)
    await message.reply_text(
        f"✅ *Trade #{trade['id']} Updated!*\n  🛑 New SL: `{new_sl}`\n  🎯 New TP: `{new_tp}`",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── /closetrade ───────────────────────────────────────────────────────

async def conv_closetrade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: `/closetrade <id>`", parse_mode="Markdown")
        return ConversationHandler.END

    try:
        trade_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID must be a number.")
        return ConversationHandler.END

    trades = db.list_open_trades(_db_conn)
    trade = next((t for t in trades if t["id"] == trade_id), None)
    if not trade:
        await update.message.reply_text(f"❌ No open trade found with ID #{trade_id}.")
        return ConversationHandler.END

    context.user_data["trade"] = dict(trade)
    await update.message.reply_text(
        f"🚪 *Manual Close for Trade #{trade_id}*\n\nAt what exact price did you close this trade on your exchange?",
        parse_mode="Markdown"
    )
    return C_PRICE

async def conv_closetrade_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        closed_price = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return C_PRICE

    trade = context.user_data["trade"]
    entry = trade["entry_price"]
    
    if trade["side"] == "long":
        pnl_pct = (closed_price - entry) / entry * 100
    else:
        pnl_pct = (entry - closed_price) / entry * 100

    db.close_trade(_db_conn, trade["id"], closed_price, pnl_pct)
    
    sign = "+" if pnl_pct > 0 else ""
    emoji = "🟢" if pnl_pct > 0 else "🔴"
    
    await update.message.reply_text(
        f"✅ *Trade #{trade['id']} Closed Manually!*\n\n"
        f"  🚪 Exit Price: `{closed_price}`\n"
        f"  💸 Final PnL: *{sign}{pnl_pct:.2f}%* {emoji}",
        parse_mode="Markdown"
    )
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
        lines.append(f'#{a["id"]} *{a["symbol"]}* `{a["exchange"]}`  target=`{a["target_price"]}` range=`{a["range_pct"]}%`{note_str}')
    buttons = [InlineKeyboardButton(f"❌ #{a['id']}", callback_data=f"dela_{a['id']}") for a in active]
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    footer = f"\n\n_{triggered_count} triggered alert(s) hidden._" if triggered_count else ""
    await update.message.reply_text("\n\n".join(lines) + footer, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_listtrades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trades = db.list_open_trades(_db_conn)
    if not trades:
        await update.message.reply_text("No open trades being tracked.")
        return
    lines = []
    for t in trades:
        price = db.get_latest_price(_db_conn, t["exchange"], t["symbol"])
        risk = abs(t["entry_price"] - t["stop_loss"])
        reward = abs(t["take_profit"] - t["entry_price"])
        rr_str = f"1:{reward/risk:.2f}" if risk > 0 else "N/A"
        pnl_str = "Waiting for price tick..."
        if price is not None:
            pnl_pct = ((price - t["entry_price"]) / t["entry_price"] * 100) if t["side"] == "long" else ((t["entry_price"] - price) / t["entry_price"] * 100)
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
            f"RR: `{rr_str}`\n{pnl_str}"
        )
    buttons = [InlineKeyboardButton(f"❌ #{t['id']}", callback_data=f"delt_{t['id']}") for t in trades]
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# ── Inline callbacks & Notifications ──────────────────────────────────

async def btn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data.startswith("dela_"):
        try:
            alert_id = int(query.data.split("_")[1])
            if db.delete_alert(_db_conn, alert_id):
                await query.message.reply_text(f"✅ Alert #{alert_id} deleted.")
        except ValueError: pass
    elif query.data.startswith("delt_"):
        try:
            trade_id = int(query.data.split("_")[1])
            _db_conn.execute("DELETE FROM trades WHERE id=?", (trade_id,))
            _db_conn.commit()
            await query.message.reply_text(f"✅ Trade Tracking #{trade_id} cancelled (deleted).")
        except ValueError: pass

_bot_app: Application | None = None

async def send_telegram_alert(alert, price: float) -> None:
    if _bot_app is None: return
    note_str = f'\n📝 {alert["note"]}' if alert["note"] else ""
    message = (
        f'🚨 *Alert #{alert["id"]} TRIGGERED*\n  📈 {alert["symbol"]} on {alert["exchange"]}\n'
        f'  💰 Price: `{price}`\n  🎯 Target: `{alert["target_price"]}` ±`{alert["range_pct"]}%`{note_str}'
    )
    await _bot_app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")

async def send_telegram_trade_close(trade, price: float, pnl_pct: float, is_tp: bool) -> None:
    if _bot_app is None: return
    emoji, reason = ("🟢", "TAKE PROFIT (TP)") if is_tp else ("🔴", "STOP LOSS (SL)")
    sign = "+" if pnl_pct > 0 else ""
    message = (
        f'{emoji} *TRADE #{trade["id"]} AUTO-CLOSED*\n\n  *Hit {reason}*\n'
        f'  {trade["side"].upper()} {trade["symbol"]} on {trade["exchange"]}\n'
        f'  Closed Price: `{price}`\n  Final PnL: *{sign}{pnl_pct:.2f}%*'
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

    updatetrade_conv = ConversationHandler(
        entry_points=[CommandHandler("updatetrade", conv_updatetrade_start)],
        states={
            U_SL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, conv_updatetrade_sl),
                CallbackQueryHandler(conv_updatetrade_sl_skip, pattern="^skip_sl$")
            ],
            U_TP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, conv_updatetrade_tp),
                CallbackQueryHandler(conv_updatetrade_tp_skip, pattern="^skip_tp$")
            ],
        },
        fallbacks=[CommandHandler("cancel", conv_cancel)],
    )

    closetrade_conv = ConversationHandler(
        entry_points=[CommandHandler("closetrade", conv_closetrade_start)],
        states={
            C_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_closetrade_price)]
        },
        fallbacks=[CommandHandler("cancel", conv_cancel)],
    )

    app.add_handler(newalert_conv)
    app.add_handler(newtrade_conv)
    app.add_handler(updatetrade_conv)
    app.add_handler(closetrade_conv)
    app.add_handler(CommandHandler("listalerts", cmd_listalerts))
    app.add_handler(CommandHandler("listtrades", cmd_listtrades))
    app.add_handler(CallbackQueryHandler(btn_callback))

    _bot_app = app
    return app
