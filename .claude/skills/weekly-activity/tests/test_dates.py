"""Date handling: UTC->local conversion, inclusive range checks."""

import pytest


# --- parse_date -------------------------------------------------------------

def test_parse_date_shifts_utc_into_local_day(ga):
    # 03:48 UTC is still the previous day at UTC-5
    assert ga.dates.parse_date("2026-04-04T03:48:35Z") == "2026-04-03"


def test_parse_date_keeps_same_day_for_midday_utc(ga):
    assert ga.dates.parse_date("2026-04-04T12:00:00Z") == "2026-04-04"


def test_parse_date_accepts_explicit_offset_form(ga):
    assert ga.dates.parse_date("2026-04-04T03:48:35+00:00") == "2026-04-03"


def test_parse_date_respects_non_utc_offsets(ga):
    # 00:30 at UTC+2 == 17:30 the previous day at UTC-5
    assert ga.dates.parse_date("2026-04-04T00:30:00+02:00") == "2026-04-03"


@pytest.mark.parametrize("value", [None, ""])
def test_parse_date_returns_none_for_missing_input(ga, value):
    assert ga.dates.parse_date(value) is None


def test_parse_date_falls_back_to_first_ten_chars_when_unparseable(ga):
    assert ga.dates.parse_date("2026-04-04 not-a-timestamp") == "2026-04-04"


# --- date_in_range ----------------------------------------------------------

@pytest.mark.parametrize("day,expected", [
    ("2026-04-05", False),   # day before
    ("2026-04-06", True),    # inclusive start
    ("2026-04-08", True),
    ("2026-04-10", True),    # inclusive end
    ("2026-04-11", False),   # day after
])
def test_date_in_range_boundaries_are_inclusive(ga, day, expected):
    assert ga.dates.date_in_range(day, "2026-04-06", "2026-04-10") is expected


def test_date_in_range_rejects_none(ga):
    assert ga.dates.date_in_range(None, "2026-04-06", "2026-04-10") is False
