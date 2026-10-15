from datetime import datetime, timezone

from ayesha.sessions import SessionEngine


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_london_open_moves_with_dst(spec):
    s = SessionEngine(spec)
    # winter: London 08:00 GMT = 08:00 UTC; summer: 08:00 BST = 07:00 UTC
    assert "LONDON" not in s.active(utc(2025, 1, 15, 7, 30))
    assert "LONDON" in s.active(utc(2025, 1, 15, 8, 0))
    assert "LONDON" in s.active(utc(2025, 7, 15, 7, 0))
    assert "LONDON" not in s.active(utc(2025, 7, 15, 6, 59))


def test_new_york_dst(spec):
    s = SessionEngine(spec)
    assert "NEW_YORK" in s.active(utc(2025, 7, 15, 12, 0))   # 08:00 EDT
    assert "NEW_YORK" not in s.active(utc(2025, 1, 15, 12, 30))  # 07:30 EST
    assert "NEW_YORK" in s.active(utc(2025, 1, 15, 13, 0))


def test_market_week(spec):
    s = SessionEngine(spec)
    assert not s.market_open(utc(2025, 7, 19, 12, 0))   # Saturday
    assert not s.market_open(utc(2025, 7, 18, 21, 30))  # Friday 17:30 New York
    assert s.market_open(utc(2025, 7, 18, 20, 30))      # Friday 16:30 New York
    assert not s.market_open(utc(2025, 7, 20, 20, 30))  # Sunday 16:30 New York
    assert s.market_open(utc(2025, 7, 20, 21, 30))      # Sunday 17:30 New York
    assert s.status(utc(2025, 7, 19, 12, 0)) == "CLOSED"


def test_rollover_and_tradeable(spec):
    s = SessionEngine(spec)
    assert s.status(utc(2025, 7, 15, 21, 0)) == "ROLLOVER"  # 17:00 New York
    assert s.tradeable(utc(2025, 7, 15, 9, 0))
    assert not s.tradeable(utc(2025, 7, 15, 2, 0))  # Tokyo only


def test_trading_day_starts_17_new_york(spec):
    s = SessionEngine(spec)
    assert s.trading_day(utc(2025, 7, 15, 20, 59)) == utc(2025, 7, 14, 21, 0)
    assert s.trading_day(utc(2025, 7, 15, 21, 0)) == utc(2025, 7, 15, 21, 0)
    assert s.trading_day(utc(2025, 1, 15, 22, 0)) == utc(2025, 1, 15, 22, 0)
