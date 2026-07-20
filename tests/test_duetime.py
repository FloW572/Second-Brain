from datetime import datetime

from app.duetime import parse_due

TZ = "Europe/Vienna"


def test_none_returns_none():
    assert parse_due(None, TZ) is None
    assert parse_due("", TZ) is None


def test_date_only_defaults_to_0900_local():
    dt = parse_due("2026-07-21", TZ)
    assert isinstance(dt, datetime)
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 7, 21, 9, 0)
    assert dt.tzinfo is not None


def test_datetime_keeps_time():
    dt = parse_due("2026-07-21T19:30", TZ)
    assert (dt.hour, dt.minute) == (19, 30)
    assert dt.tzinfo is not None


def test_garbage_returns_none():
    assert parse_due("übermorgen abend", TZ) is None
