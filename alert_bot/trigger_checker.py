"""Core trigger logic — DO NOT modify conditions without re-verifying the spec.

This is the highest-risk file in the project. Changes here can make alerts
silently fire wrong (or silently never fire) without raising any errors.

Locked spec:
  - One-shot alerts: fire once, mark triggered, never fire again.
  - Band-based only: target_price ± range_pct%.
  - Two trigger conditions:
      1. Current price is inside the band.
      2. Price gapped through the band between consecutive ticks.
"""

from __future__ import annotations

import logging

from alert_bot import db

logger = logging.getLogger("conflux.trigger")


def check_trigger(
    prev_price: float | None,
    curr_price: float,
    target_price: float,
    range_pct: float,
) -> bool:
    """Check if a price tick triggers an alert band.

    Returns True if:
      1. curr_price is inside [target*(1 - range_pct/100), target*(1 + range_pct/100)]
      2. Price gapped through the band (prev on one side, curr on the other,
         neither inside)

    Args:
        prev_price: Previous tick price, or None if first tick after restart.
        curr_price: Current tick price.
        target_price: Alert target price.
        range_pct: Alert band width as a percentage of target_price.
    """
    lower = target_price * (1 - range_pct / 100)
    upper = target_price * (1 + range_pct / 100)

    # Condition 1: price currently inside band
    inside_band = lower <= curr_price <= upper
    if inside_band:
        return True

    # Condition 2: price gapped through the band between ticks
    if prev_price is not None:
        crossed_upward = prev_price < lower and curr_price > upper
        crossed_downward = prev_price > upper and curr_price < lower
        if crossed_upward or crossed_downward:
            return True

    return False


async def process_tick(
    exchange: str,
    symbol: str,
    price: float,
    db_conn,
    last_price_dict: dict,
    send_alert_fn,
) -> None:
    """Process a single price tick: check triggers, send alerts, log price.

    CRITICAL: last_price_dict[key] = price MUST run every tick, unconditionally,
    even if no alert matched. If this line only runs inside a conditional,
    gap-detection silently breaks on the next tick.

    Args:
        exchange: Exchange name (lowercase).
        symbol: Trading pair symbol.
        price: Current price as float.
        db_conn: SQLite connection.
        last_price_dict: Shared mutable dict of (exchange, symbol) -> last price.
        send_alert_fn: Async callable(alert_row, price) to send Telegram notification.
    """
    key = (exchange, symbol)
    prev_price = last_price_dict.get(key)

    alerts = db.get_active_alerts(db_conn, exchange, symbol)

    for alert in alerts:
        if check_trigger(prev_price, price, alert["target_price"], alert["range_pct"]):
            logger.info(
                "TRIGGERED alert #%d: %s %s price=%.8g target=%.8g range=%.4g%%",
                alert["id"],
                exchange,
                symbol,
                price,
                alert["target_price"],
                alert["range_pct"],
            )
            try:
                await send_alert_fn(alert, price)
            except Exception:
                logger.exception("Failed to send Telegram alert for #%d", alert["id"])
            db.mark_triggered(db_conn, alert["id"])

    # CRITICAL: update last price UNCONDITIONALLY — gap-detection depends on this.
    last_price_dict[key] = price

    db.log_price(db_conn, exchange, symbol, price)
