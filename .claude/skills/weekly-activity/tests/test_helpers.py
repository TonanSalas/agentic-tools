"""Pure-function helpers: date handling, title/ref parsing, cache paths."""

import os
import time

import pytest


# --- parse_date -------------------------------------------------------------

def test_parse_date_shifts_utc_into_local_day(ga):
    # 03:48 UTC is still the previous day at UTC-5
    assert ga.parse_date("2026-04-04T03:48:35Z") == "2026-04-03"


def test_parse_date_keeps_same_day_for_midday_utc(ga):
    assert ga.parse_date("2026-04-04T12:00:00Z") == "2026-04-04"


def test_parse_date_accepts_explicit_offset_form(ga):
    assert ga.parse_date("2026-04-04T03:48:35+00:00") == "2026-04-03"


def test_parse_date_respects_non_utc_offsets(ga):
    # 00:30 at UTC+2 == 17:30 the previous day at UTC-5
    assert ga.parse_date("2026-04-04T00:30:00+02:00") == "2026-04-03"


@pytest.mark.parametrize("value", [None, ""])
def test_parse_date_returns_none_for_missing_input(ga, value):
    assert ga.parse_date(value) is None


def test_parse_date_falls_back_to_first_ten_chars_when_unparseable(ga):
    assert ga.parse_date("2026-04-04 not-a-timestamp") == "2026-04-04"


# --- date_in_range ----------------------------------------------------------

@pytest.mark.parametrize("day,expected", [
    ("2026-04-05", False),   # day before
    ("2026-04-06", True),    # inclusive start
    ("2026-04-08", True),
    ("2026-04-10", True),    # inclusive end
    ("2026-04-11", False),   # day after
])
def test_date_in_range_boundaries_are_inclusive(ga, day, expected):
    assert ga.date_in_range(day, "2026-04-06", "2026-04-10") is expected


def test_date_in_range_rejects_none(ga):
    assert ga.date_in_range(None, "2026-04-06", "2026-04-10") is False


# --- strip_conventional_prefix ---------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("feat: add widget", "add widget"),
    ("fix(api): handle nulls", "handle nulls"),
    ("CHORE: bump deps", "bump deps"),
    ("Refactor(core): tidy up", "tidy up"),
    ("revert: undo that", "undo that"),
])
def test_strip_conventional_prefix_removes_known_prefixes(ga, title, expected):
    assert ga.strip_conventional_prefix(title) == expected


@pytest.mark.parametrize("title", [
    "Add widget",                 # no prefix at all
    "features: not conventional", # not in the allowed set
    "wip: also not in the set",
    "later feat: mid-string",     # only anchored prefixes are stripped
])
def test_strip_conventional_prefix_leaves_other_titles_alone(ga, title):
    assert ga.strip_conventional_prefix(title) == title


def test_strip_conventional_prefix_strips_only_the_outermost_prefix(ga):
    assert ga.strip_conventional_prefix("feat: fix: double") == "fix: double"


# --- extract_ticket_refs ---------------------------------------------------

def test_extract_ticket_refs_finds_all_occurrences_in_order(ga):
    assert ga.extract_ticket_refs("closes #101, see also #7 and #101") == [101, 7, 101]


@pytest.mark.parametrize("text", [None, "", "no refs here", "#notanumber"])
def test_extract_ticket_refs_returns_empty_when_nothing_matches(ga, text):
    assert ga.extract_ticket_refs(text) == []


def test_extract_ticket_refs_reads_digits_glued_to_words(ga):
    # documents current behaviour: the regex is not word-boundary anchored
    assert ga.extract_ticket_refs("PR#42") == [42]


# --- cache -----------------------------------------------------------------

def test_cache_path_for_names_file_by_date_range(ga, tmp_path):
    path = ga.cache_path_for(tmp_path, "2026-04-06", "2026-04-10")
    assert path == tmp_path / "2026-04-06_2026-04-10.json"


def test_cache_is_stale_when_file_absent(ga, tmp_path):
    assert ga.cache_is_fresh(tmp_path / "missing.json", "2020-01-01") is False


def test_closed_week_cache_is_fresh_regardless_of_age(ga, tmp_path):
    path = tmp_path / "old.json"
    path.write_text("{}")
    ancient = time.time() - 10 * 365 * 24 * 3600
    os.utime(path, (ancient, ancient))
    assert ga.cache_is_fresh(path, "2020-01-01") is True


def test_open_week_cache_is_fresh_within_ttl(ga, tmp_path):
    path = tmp_path / "recent.json"
    path.write_text("{}")
    assert ga.cache_is_fresh(path, "2999-01-01") is True


def test_open_week_cache_expires_after_ttl(ga, tmp_path):
    path = tmp_path / "stale.json"
    path.write_text("{}")
    old = time.time() - (ga.CACHE_TTL_SECONDS + 60)
    os.utime(path, (old, old))
    assert ga.cache_is_fresh(path, "2999-01-01") is False
