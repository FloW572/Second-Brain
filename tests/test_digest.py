from datetime import date, datetime, timezone

from app.digest import _should_send

DIGEST_HOUR = 8


def _at(hour):
    return datetime(2026, 7, 21, hour, 0, tzinfo=timezone.utc)


def test_sends_during_digest_hour_when_not_sent_today():
    assert _should_send(_at(8), None, DIGEST_HOUR) is True


def test_not_sent_outside_digest_hour():
    assert _should_send(_at(9), None, DIGEST_HOUR) is False
    assert _should_send(_at(7), None, DIGEST_HOUR) is False


def test_not_sent_twice_same_day():
    now = _at(8)
    assert _should_send(now, now.date(), DIGEST_HOUR) is False


def test_sends_again_next_day():
    now = _at(8)
    yesterday = date(2026, 7, 20)
    assert _should_send(now, yesterday, DIGEST_HOUR) is True
