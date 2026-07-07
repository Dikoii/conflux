"""Bitget V2 WebSocket — public ticker stream.

Verified against current Bitget V2 docs (July 2026):
  - Endpoint: wss://ws.bitget.com/v2/ws/public
  - Channel: ticker
  - Subscribe: {"op":"subscribe","args":[{"instType":"SPOT","channel":"ticker","instId":"BTCUSDT"}]}
  - Price field: "last" (in data[0], returned as string → must cast to float)
  - Symbol field: "instId" (in data[0])
  - MUST send "ping" string every 30s to keep connection alive
  - Max 1000 channels per connection, recommended <50 for stability
"""

from __future__ import annotations

import asyncio
import json
import logging

from alert_bot.exchange_ws import run_forever

logger = logging.getLogger("conflux.ws.bitget")

ENDPOINT = "wss://ws.bitget.com/v2/ws/public"
EXCHANGE_NAME = "bitget"
PING_INTERVAL = 25  # seconds, slightly under 30s deadline


async def start_bitget(
    initial_symbols: list[str],
    subscribe_queue: asyncio.Queue,
    process_tick_fn,
) -> None:
    """Run the Bitget websocket connection forever.

    Args:
        initial_symbols: Symbols to subscribe on connect (e.g. ["BTCUSDT"]).
        subscribe_queue: Queue receiving ("subscribe", symbol) tuples from Telegram handler.
        process_tick_fn: Async callable(exchange, symbol, price) to process each tick.
    """
    subscribed: set[str] = set()
    ping_task: asyncio.Task | None = None
    ws_ref = None

    async def _keepalive(ws) -> None:
        """Send 'ping' string every PING_INTERVAL seconds to keep connection alive."""
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                await ws.send("ping")
        except (asyncio.CancelledError, Exception):
            pass

    async def _subscribe(ws, symbols: list[str]) -> None:
        new_symbols = [s for s in symbols if s not in subscribed]
        if not new_symbols:
            return

        args = [
            {"instType": "SPOT", "channel": "ticker", "instId": s}
            for s in new_symbols
        ]
        msg = json.dumps({"op": "subscribe", "args": args})
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
        nonlocal ping_task, listener_task
        
        if listener_task:
            listener_task.cancel()
        listener_task = asyncio.create_task(queue_listener(ws))

        subscribed.clear()

        # Start keepalive ping task
        if ping_task is not None:
            ping_task.cancel()
        ping_task = asyncio.create_task(_keepalive(ws))

        await _subscribe(ws, initial_symbols)

    async def on_message(raw: str) -> None:

        # Handle pong response
        if raw == "pong":
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        # Skip subscription confirmation responses
        if data.get("event") in ("subscribe", "error"):
            if data.get("event") == "error":
                logger.error("Bitget subscribe error: %s", data)
            return

        # Extract ticker data
        action = data.get("action")
        inner_data = data.get("data")
        if not inner_data or not isinstance(inner_data, list):
            return

        for tick in inner_data:
            inst_id = tick.get("instId")
            price_str = tick.get("last")

            if inst_id is None or price_str is None:
                continue

            try:
                price = float(price_str)
            except (ValueError, TypeError):
                logger.warning("Bad price value from Bitget: %s", price_str)
                continue

            await process_tick_fn(EXCHANGE_NAME, inst_id, price)

    try:
        await run_forever(ENDPOINT, on_connect, on_message, name="bitget")
    finally:
        if ping_task is not None:
            ping_task.cancel()
