from datetime import date, datetime, timezone

from app.digest import _should_send_daily, _should_send_weekly

DIGEST_HOUR = 8
REVIEW_WEEKDAY = 6  # Sunday
REVIEW_HOUR = 18


def _at(hour, day=21):  # 2026-07-21 is a Tuesday; 2026-07-19 a Sunday
    return datetime(2026, 7, day, hour, 0, tzinfo=timezone.utc)


# --- daily digest ---

def test_daily_sends_during_hour_when_not_sent_today():
    assert _should_send_daily(_at(8), None, DIGEST_HOUR) is True


def test_daily_not_sent_outside_hour():
    assert _should_send_daily(_at(9), None, DIGEST_HOUR) is False
    assert _should_send_daily(_at(7), None, DIGEST_HOUR) is False


def test_daily_not_sent_twice_same_day():
    now = _at(8)
    assert _should_send_daily(now, now.date(), DIGEST_HOUR) is False


def test_daily_sends_again_next_day():
    assert _should_send_daily(_at(8), date(2026, 7, 20), DIGEST_HOUR) is True


# --- weekly review (Sunday = 2026-07-19) ---

def test_weekly_sends_on_weekday_and_hour():
    sunday = _at(REVIEW_HOUR, day=19)
    assert _should_send_weekly(sunday, None, REVIEW_WEEKDAY, REVIEW_HOUR) is True


def test_weekly_not_sent_on_wrong_weekday():
    tuesday = _at(REVIEW_HOUR, day=21)
    assert _should_send_weekly(tuesday, None, REVIEW_WEEKDAY, REVIEW_HOUR) is False


def test_weekly_not_sent_wrong_hour():
    sunday = _at(REVIEW_HOUR + 1, day=19)
    assert _should_send_weekly(sunday, None, REVIEW_WEEKDAY, REVIEW_HOUR) is False


def test_weekly_not_sent_twice_same_day():
    sunday = _at(REVIEW_HOUR, day=19)
    assert _should_send_weekly(sunday, sunday.date(), REVIEW_WEEKDAY, REVIEW_HOUR) is False
