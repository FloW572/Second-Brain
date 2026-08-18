from datetime import date

from app.ingest.normalize import normalize_capture, normalize_occasion
from app.occasions import days_until, format_occasion, is_due, next_occurrence

# --- nächste Wiederholung ---


def test_upcoming_date_stays_in_current_year():
    assert next_occurrence(5, 17, date(2026, 3, 1)) == date(2026, 5, 17)


def test_today_counts_as_upcoming():
    assert next_occurrence(5, 17, date(2026, 5, 17)) == date(2026, 5, 17)


def test_past_date_rolls_into_next_year():
    assert next_occurrence(5, 17, date(2026, 5, 18)) == date(2027, 5, 17)


def test_leap_day_falls_back_to_28th_in_normal_years():
    assert next_occurrence(2, 29, date(2026, 1, 1)) == date(2026, 2, 28)
    assert next_occurrence(2, 29, date(2028, 1, 1)) == date(2028, 2, 29)


def test_days_until_counts_forward():
    assert days_until(5, 17, date(2026, 5, 3)) == 14


# --- Fälligkeit der Vorlauf-Erinnerung ---


def test_not_due_before_lead_window():
    assert is_due(5, 17, 14, None, date(2026, 5, 2)) is False


def test_due_when_lead_window_starts():
    assert is_due(5, 17, 14, None, date(2026, 5, 3)) is True


def test_not_due_twice_in_the_same_window():
    assert is_due(5, 17, 14, date(2026, 5, 3), date(2026, 5, 6)) is False


def test_due_again_next_year():
    assert is_due(5, 17, 14, date(2026, 5, 3), date(2027, 5, 3)) is True


def test_still_due_on_the_day_itself_if_never_reminded():
    assert is_due(5, 17, 14, None, date(2026, 5, 17)) is True


# --- Formatierung ---


def test_format_uses_relative_wording():
    occasion = {"id": 3, "label": "Luisa Geburtstag", "kind": "birthday",
                "month": 5, "day": 17, "days_until": 12}
    assert format_occasion(occasion) == "🎂 #3 Luisa Geburtstag · 17.05. · in 12 Tagen"


def test_format_says_today_at_zero_days():
    occasion = {"id": 1, "label": "Jahrestag", "kind": "anniversary",
                "month": 8, "day": 18, "days_until": 0}
    assert format_occasion(occasion).endswith("· heute")


# --- Extraktion aus einer erfassten Nachricht ---


def test_occasion_is_kept_when_day_and_month_are_usable():
    result = normalize_occasion({"label": "Luisa Geburtstag", "person": "Luisa",
                                 "kind": "birthday", "month": 5, "day": 17})
    assert result == {"label": "Luisa Geburtstag", "person": "Luisa",
                      "kind": "birthday", "month": 5, "day": 17}


def test_occasion_label_falls_back_to_person():
    assert normalize_occasion({"person": "Luisa", "month": 5, "day": 17})["label"] \
        == "Luisa Geburtstag"


def test_occasion_dropped_when_date_is_unusable():
    assert normalize_occasion({"label": "X", "month": 13, "day": 1}) is None
    assert normalize_occasion({"label": "X", "month": 5}) is None
    assert normalize_occasion(None) is None


def test_unknown_kind_becomes_custom():
    assert normalize_occasion({"label": "X", "kind": "namensfeier",
                               "month": 5, "day": 17})["kind"] == "custom"


def test_capture_without_occasion_has_none():
    assert normalize_capture({"type": "note", "title": "Test"}, "Test")["occasion"] is None
