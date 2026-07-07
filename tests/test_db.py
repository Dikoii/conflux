"""Smoke tests for the DB layer — create, list, delete, mark triggered."""

import sys
import os
import sqlite3
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Override DB_PATH before importing db module
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_alerts.db")

from alert_bot import db


def test_init_and_create():
    conn = db.get_connection()
    db.init_db(conn)

    # Create an alert
    aid = db.create_alert(conn, "BTCUSDT", "binance", 65000.0, 2.0, "test note")
    assert aid is not None and aid > 0, f"Expected positive ID, got {aid}"

    # List it
    alerts = db.list_alerts(conn)
    assert len(alerts) == 1, f"Expected 1 alert, got {len(alerts)}"
    assert alerts[0]["symbol"] == "BTCUSDT"
    assert alerts[0]["exchange"] == "binance"
    assert alerts[0]["target_price"] == 65000.0
    assert alerts[0]["range_pct"] == 2.0
    assert alerts[0]["note"] == "test note"
    assert alerts[0]["status"] == "active"

    conn.close()


def test_delete():
    conn = db.get_connection()

    aid = db.create_alert(conn, "ETHUSDT", "okx", 3200.0, 3.0, None)

    # Delete it
    assert db.delete_alert(conn, aid) is True
    # Delete again — should return False
    assert db.delete_alert(conn, aid) is False
    # Delete non-existent
    assert db.delete_alert(conn, 99999) is False

    conn.close()


def test_mark_triggered():
    conn = db.get_connection()

    aid = db.create_alert(conn, "SOLUSDT", "bitget", 150.0, 5.0, "sol watch")

    # Should be active
    active = db.get_active_alerts(conn, "bitget", "SOLUSDT")
    assert len(active) == 1

    # Mark triggered
    db.mark_triggered(conn, aid)

    # Should no longer be active
    active = db.get_active_alerts(conn, "bitget", "SOLUSDT")
    assert len(active) == 0

    # But should still appear in list
    all_alerts = db.list_alerts(conn)
    triggered = [a for a in all_alerts if a["id"] == aid]
    assert len(triggered) == 1
    assert triggered[0]["status"] == "triggered"
    assert triggered[0]["triggered_at"] is not None

    conn.close()


def test_active_symbols():
    conn = db.get_connection()

    db.create_alert(conn, "XRPUSDT", "binance", 1.0, 10.0, None)
    db.create_alert(conn, "XRPUSDT", "binance", 1.5, 5.0, None)  # same pair
    db.create_alert(conn, "DOTUSDT", "okx", 8.0, 3.0, None)

    pairs = db.get_active_symbols(conn)
    # Should have XRPUSDT/binance and DOTUSDT/okx (deduplicated)
    assert ("binance", "XRPUSDT") in pairs
    assert ("okx", "DOTUSDT") in pairs

    conn.close()


def test_price_log():
    conn = db.get_connection()

    db.log_price(conn, "binance", "BTCUSDT", 65123.45)

    rows = conn.execute("SELECT * FROM price_log WHERE symbol='BTCUSDT'").fetchall()
    assert len(rows) >= 1
    assert rows[-1]["price"] == 65123.45

    conn.close()


if __name__ == "__main__":
    tests = [
        test_init_and_create,
        test_delete,
        test_mark_triggered,
        test_active_symbols,
        test_price_log,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✅ {test.__name__}")
            passed += 1
        except (AssertionError, Exception) as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed > 0 else 0)
