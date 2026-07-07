"""OKX V5 WebSocket — public tickers channel.

Verified against current OKX V5 docs (July 2026):
  - Endpoint: wss://ws.okx.com:8443/ws/v5/public
  - Channel: tickers
  - Subscribe: {"op":"subscribe","args":[{"channel":"tickers","instId":"BTC-USDT"}]}
  - Price field: "last" (in data[0], returned as string → must cast to float)
  - Symbol field: "instId" (in data[0])
  - OKX uses HYPHENATED pairs: BTC-USDT, not BTCUSDT
  - Updates every ~100ms on price change
  - OKX handles ping/pong at the protocol level
"""

from __future__ import annotations

import asyncio
import json
import logging

from alert_bot.exchange_ws import run_forever

logger = logging.getLogger("conflux.ws.okx")

ENDPOINT = "wss://ws.okx.com:8443/ws/v5/public"
EXCHANGE_NAME = "okx"


async def start_okx(
    initial_symbols: list[str],
    subscribe_queue: asyncio.Queue,
    process_tick_fn,
) -> None:
    """Run the OKX websocket connection forever.

    Args:
        initial_symbols: Symbols to subscribe on connect (e.g. ["BTC-USDT"]).
                         Note: OKX uses hyphenated pairs.
        subscribe_queue: Queue receiving ("subscribe", symbol) tuples from Telegram handler.
        process_tick_fn: Async callable(exchange, symbol, price) to process each tick.
    """
    subscribed: set[str] = set()
    ws_ref = None

    async def _subscribe(ws, symbols: list[str]) -> None:
        new_symbols = [s for s in symbols if s not in subscribed]
        if not new_symbols:
            return

        args = [{"channel": "tickers", "instId": s} for s in new_symbols]
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

        # Skip subscription confirmation / error responses
        if "event" in data:
            if data["event"] == "error":
                logger.error("OKX subscribe error: %s", data)
            return

        # Extract ticker data
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
                logger.warning("Bad price value from OKX: %s", price_str)
                continue

            await process_tick_fn(EXCHANGE_NAME, inst_id, price)

    await run_forever(ENDPOINT, on_connect, on_message, name="okx")
