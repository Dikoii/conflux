"""Tests for check_trigger() — the highest-risk function in the project.

Test cases cover:
  - Price inside band → True
  - Price outside band (above) → False
  - Price outside band (below) → False
  - Gap through upward (prev < lower, curr > upper) → True
  - Gap through downward (prev > upper, curr < lower) → True
  - prev_price=None, price inside → True
  - prev_price=None, price outside → False
  - Edge cases: price exactly on band boundary
"""

import sys
import os

# Add project root to path so we can import alert_bot
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alert_bot.trigger_checker import check_trigger


def test_inside_band():
    """Price currently inside band → should trigger."""
    # target=100, range=5% → band is [95, 105]
    assert check_trigger(None, 100.0, 100.0, 5.0) is True  # dead center
    assert check_trigger(None, 95.0, 100.0, 5.0) is True   # lower boundary
    assert check_trigger(None, 105.0, 100.0, 5.0) is True  # upper boundary
    assert check_trigger(None, 97.5, 100.0, 5.0) is True   # inside
    assert check_trigger(80.0, 100.0, 100.0, 5.0) is True  # inside, with prev


def test_outside_band():
    """Price outside band, no gap-through → should NOT trigger."""
    # target=100, range=5% → band is [95, 105]
    assert check_trigger(None, 94.99, 100.0, 5.0) is False  # just below
    assert check_trigger(None, 105.01, 100.0, 5.0) is False  # just above
    assert check_trigger(None, 50.0, 100.0, 5.0) is False    # way below
    assert check_trigger(None, 200.0, 100.0, 5.0) is False   # way above


def test_outside_with_prev_same_side():
    """Price and prev both on same side of band → no gap, should NOT trigger."""
    # target=100, range=5% → band is [95, 105]
    assert check_trigger(90.0, 94.0, 100.0, 5.0) is False   # both below
    assert check_trigger(110.0, 106.0, 100.0, 5.0) is False  # both above


def test_gap_through_upward():
    """Price gapped through band upward (prev < lower, curr > upper) → True."""
    # target=100, range=5% → band is [95, 105]
    assert check_trigger(90.0, 110.0, 100.0, 5.0) is True
    assert check_trigger(94.99, 105.01, 100.0, 5.0) is True  # just barely


def test_gap_through_downward():
    """Price gapped through band downward (prev > upper, curr < lower) → True."""
    # target=100, range=5% → band is [95, 105]
    assert check_trigger(110.0, 90.0, 100.0, 5.0) is True
    assert check_trigger(105.01, 94.99, 100.0, 5.0) is True  # just barely


def test_no_gap_partial_cross():
    """Price crossed into band from outside but didn't gap through → inside triggers."""
    # target=100, range=5% → band is [95, 105]
    # prev below, curr inside → triggers because curr is inside band
    assert check_trigger(90.0, 97.0, 100.0, 5.0) is True
    # prev above, curr inside → triggers because curr is inside band
    assert check_trigger(110.0, 103.0, 100.0, 5.0) is True


def test_prev_none_no_gap_detection():
    """With prev_price=None, only condition 1 (inside) applies."""
    # target=100, range=5% → band is [95, 105]
    assert check_trigger(None, 100.0, 100.0, 5.0) is True   # inside
    assert check_trigger(None, 110.0, 100.0, 5.0) is False   # outside, no prev


def test_narrow_band():
    """Very narrow band (0.1%) still works correctly."""
    # target=50000, range=0.1% → band is [49950, 50050]
    assert check_trigger(None, 50000.0, 50000.0, 0.1) is True   # inside
    assert check_trigger(None, 49949.0, 50000.0, 0.1) is False  # outside
    assert check_trigger(49900.0, 50100.0, 50000.0, 0.1) is True  # gap through


def test_wide_band():
    """Very wide band (50%) works correctly."""
    # target=100, range=50% → band is [50, 150]
    assert check_trigger(None, 100.0, 100.0, 50.0) is True
    assert check_trigger(None, 50.0, 100.0, 50.0) is True
    assert check_trigger(None, 150.0, 100.0, 50.0) is True
    assert check_trigger(None, 49.0, 100.0, 50.0) is False
    assert check_trigger(None, 151.0, 100.0, 50.0) is False


if __name__ == "__main__":
    tests = [
        test_inside_band,
        test_outside_band,
        test_outside_with_prev_same_side,
        test_gap_through_upward,
        test_gap_through_downward,
        test_no_gap_partial_cross,
        test_prev_none_no_gap_detection,
        test_narrow_band,
        test_wide_band,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✅ {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed > 0 else 0)
