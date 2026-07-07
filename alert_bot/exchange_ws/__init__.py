"""Exchange WebSocket shared utilities — reconnection wrapper with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

import websockets

logger = logging.getLogger("conflux.ws")


async def run_forever(
    endpoint: str,
    on_connect: Callable,
    on_message: Callable,
    name: str = "ws",
) -> None:
    """Connect to a websocket endpoint with exponential backoff reconnection.

    Uses exponential backoff (5s → 300s cap) instead of flat retry because:
    - If disconnect is from rate-limiting, constant retry re-triggers the limit.
    - If disconnect is transient, backoff is still fast enough (starts at 5s).

    Args:
        endpoint: WSS URL to connect to.
        on_connect: Async callable(ws) to run after connection (send subscriptions).
        on_message: Async callable(message_str) to process each incoming message.
        name: Label for log messages.
    """
    backoff = 5
    while True:
        try:
            logger.info("[%s] Connecting to %s", name, endpoint)
            async with websockets.connect(
                endpoint,
                ping_interval=20,
                ping_timeout=60,
                close_timeout=10,
            ) as ws:
                await on_connect(ws)
                backoff = 5  # reset after successful connect
                logger.info("[%s] Connected, listening for messages", name)
                async for message in ws:
                    await on_message(message)
        except (websockets.ConnectionClosed, OSError) as e:
            logger.error("[%s] Dropped: %s, retrying in %ds", name, e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
        except Exception:
            logger.exception("[%s] Unexpected error, retrying in %ds", name, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
