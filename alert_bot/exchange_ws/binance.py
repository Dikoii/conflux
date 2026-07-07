"""Binance Spot WebSocket — miniTicker stream.

Verified against current Binance Spot docs (July 2026):
  - Endpoint: wss://stream.binance.com:9443/ws
  - Stream: <symbol_lower>@miniTicker
  - Price field: "c" (last price, returned as string → must cast to float)
  - Symbol field: "s" (uppercase)
  - Subscribe: {"method":"SUBSCRIBE","params":["btcusdt@miniTicker"],"id":1}
  - Max 1024 streams per connection
  - Connection valid for 24 hours; server sends serverShutdown event before maintenance
"""

from __future__ import annotations

import asyncio
import json
import logging

from alert_bot.exchange_ws import run_forever

logger = logging.getLogger("conflux.ws.binance")

ENDPOINT = "wss://stream.binance.com:9443/ws"
EXCHANGE_NAME = "binance"


async def start_binance(
    initial_symbols: list[str],
    subscribe_queue: asyncio.Queue,
    process_tick_fn,
) -> None:
    """Run the Binance websocket connection forever.

    Args:
        initial_symbols: Symbols to subscribe on connect (e.g. ["BTCUSDT", "ETHUSDT"]).
        subscribe_queue: Queue receiving ("subscribe", symbol) tuples from Telegram handler.
        process_tick_fn: Async callable(exchange, symbol, price) to process each tick.
    """
    subscribed: set[str] = set()
    sub_id_counter = 1

    async def _subscribe(ws, symbols: list[str]) -> None:
        nonlocal sub_id_counter
        new_symbols = [s for s in symbols if s not in subscribed]
        if not new_symbols:
            return

        # Binance requires lowercase symbol in stream name
        params = [f"{s.lower()}@miniTicker" for s in new_symbols]
        msg = json.dumps({
            "method": "SUBSCRIBE",
            "params": params,
            "id": sub_id_counter,
        })
        sub_id_counter += 1
        await ws.send(msg)
        subscribed.update(new_symbols)
        logger.info("Subscribed to %s", new_symbols)

    async def queue_listener(ws):
        try:
            while True:
                action, symbol = await subscribe_queue.get()
                if action == "subscribe":
                    await _subscribe(ws, [symbol])
        except asyncio.CancelledError:
            pass

    listener_task = None

    async def on_connect(ws) -> None:
        nonlocal listener_task
        if listener_task:
            listener_task.cancel()
        listener_task = asyncio.create_task(queue_listener(ws))
        
        subscribed.clear()
        await _subscribe(ws, initial_symbols)

    async def on_message(raw: str) -> None:

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        # Skip subscription confirmation responses
        if "result" in data or "id" in data and "s" not in data:
            return

        # Skip non-miniTicker events
        event_type = data.get("e", "")
        if event_type != "24hrMiniTicker":
            return

        symbol = data.get("s")
        price_str = data.get("c")

        if symbol is None or price_str is None:
            logger.warning("Missing fields in Binance message: %s", raw[:200])
            return

        try:
            price = float(price_str)
        except (ValueError, TypeError):
            logger.warning("Bad price value from Binance: %s", price_str)
            return

        await process_tick_fn(EXCHANGE_NAME, symbol, price)

    await run_forever(ENDPOINT, on_connect, on_message, name="binance")
