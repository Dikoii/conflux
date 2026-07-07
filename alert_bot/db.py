"""SQLite database layer for alerts and price logging."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from alert_bot.config import DB_PATH


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    """Return a connection with Row factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist. Idempotent."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL,
            target_price REAL NOT NULL,
            range_pct REAL NOT NULL,
            note TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            triggered_at TEXT
        );

        CREATE TABLE IF NOT EXISTS price_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            ts TEXT NOT NULL
        );
        """
    )
    conn.commit()


def create_alert(
    conn: sqlite3.Connection,
    symbol: str,
    exchange: str,
    target_price: float,
    range_pct: float,
    note: str | None,
) -> int:
    """Insert a new alert and return its ID."""
    cursor = conn.execute(
        "INSERT INTO alerts (symbol, exchange, target_price, range_pct, note, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'active', ?)",
        (symbol, exchange, target_price, range_pct, note, _now_iso()),
    )
    conn.commit()
    return cursor.lastrowid


def list_alerts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all alerts regardless of status, ordered by ID."""
    return conn.execute("SELECT * FROM alerts ORDER BY id").fetchall()


def delete_alert(conn: sqlite3.Connection, alert_id: int) -> bool:
    """Delete an alert by ID. Returns True if a row was actually deleted."""
    result = conn.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
    conn.commit()
    return result.rowcount > 0


def get_active_alerts(
    conn: sqlite3.Connection, exchange: str, symbol: str
) -> list[sqlite3.Row]:
    """Get all active alerts for a specific exchange+symbol pair."""
    return conn.execute(
        "SELECT * FROM alerts WHERE exchange=? AND symbol=? AND status='active'",
        (exchange, symbol),
    ).fetchall()


def mark_triggered(conn: sqlite3.Connection, alert_id: int) -> None:
    """Mark an alert as triggered with current timestamp."""
    conn.execute(
        "UPDATE alerts SET status='triggered', triggered_at=? WHERE id=?",
        (_now_iso(), alert_id),
    )
    conn.commit()


def get_active_symbols(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Return distinct (exchange, symbol) pairs with active alerts."""
    rows = conn.execute(
        "SELECT DISTINCT exchange, symbol FROM alerts WHERE status='active'"
    ).fetchall()
    return [(row["exchange"], row["symbol"]) for row in rows]


def log_price(
    conn: sqlite3.Connection, exchange: str, symbol: str, price: float
) -> None:
    """Log a price tick to price_log."""
    conn.execute(
        "INSERT INTO price_log (exchange, symbol, price, ts) VALUES (?, ?, ?, ?)",
        (exchange, symbol, price, _now_iso()),
    )
    conn.commit()
