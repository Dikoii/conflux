"""Main entry point — wires up DB, exchange WS tasks, and Telegram bot."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from alert_bot import db
from alert_bot.config import logger
from alert_bot.trigger_checker import process_tick
from alert_bot.telegram_bot import (
    build_application,
    init_telegram,
    send_telegram_alert,
)
from alert_bot.exchange_ws.binance import start_binance
from alert_bot.exchange_ws.bitget import start_bitget
from alert_bot.exchange_ws.okx import start_okx

# In-memory state for gap-detection — (exchange, symbol) -> float
# Does not survive restart; first tick after restart has prev_price=None.
last_price: dict[tuple[str, str], float] = {}


async def main() -> None:
    """Startup sequence:
    1. Init DB
    2. Query active (exchange, symbol) pairs
    3. Create one asyncio.Queue per exchange
    4. Start one async task per exchange with active symbols
    5. Start Telegram bot (polling)
    6. asyncio.gather() all tasks
    """
    # 1. Init DB
    db_conn = db.get_connection()
    db.init_db(db_conn)
    logger.info("Database initialized")

    # 2. Query active symbols, grouped by exchange
    active_pairs = db.get_active_symbols(db_conn)
    symbols_by_exchange: dict[str, list[str]] = defaultdict(list)
    for exchange, symbol in active_pairs:
        symbols_by_exchange[exchange].append(symbol)

    logger.info(
        "Active symbols: %s",
        {k: v for k, v in symbols_by_exchange.items()} if symbols_by_exchange else "none",
    )

    # 3. Create one queue per exchange
    exchange_queues: dict[str, asyncio.Queue] = {
        "binance": asyncio.Queue(),
        "bitget": asyncio.Queue(),
        "okx": asyncio.Queue(),
    }

    # 4. Init Telegram shared state
    init_telegram(db_conn, exchange_queues)

    # Process tick wrapper — bridges exchange WS callback to trigger_checker
    async def on_tick(exchange: str, symbol: str, price: float) -> None:
        await process_tick(
            exchange=exchange,
            symbol=symbol,
            price=price,
            db_conn=db_conn,
            last_price_dict=last_price,
            send_alert_fn=send_telegram_alert,
        )

    # 5. Build exchange tasks
    tasks = []

    # Always start all exchange tasks (even if no active symbols yet)
    # so dynamic subscriptions from /newalert work immediately
    tasks.append(
        asyncio.create_task(
            start_binance(
                initial_symbols=symbols_by_exchange.get("binance", []),
                subscribe_queue=exchange_queues["binance"],
                process_tick_fn=on_tick,
            ),
            name="ws-binance",
        )
    )
    tasks.append(
        asyncio.create_task(
            start_bitget(
                initial_symbols=symbols_by_exchange.get("bitget", []),
                subscribe_queue=exchange_queues["bitget"],
                process_tick_fn=on_tick,
            ),
            name="ws-bitget",
        )
    )
    tasks.append(
        asyncio.create_task(
            start_okx(
                initial_symbols=symbols_by_exchange.get("okx", []),
                subscribe_queue=exchange_queues["okx"],
                process_tick_fn=on_tick,
            ),
            name="ws-okx",
        )
    )

    # 6. Start Telegram bot (polling mode — no webhook needed)
    app = build_application()
    logger.info("Starting Telegram bot (polling)")

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        logger.info("Conflux alert bot running. Press Ctrl+C to stop.")

        try:
            # Wait for all WS tasks (they run_forever, so this blocks until error/cancel)
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Shutting down...")
        finally:
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger("conflux").info("Interrupted by user")
