"""Commit-title prefix stripping and ticket-reference extraction."""

import pytest


# --- strip_conventional_prefix ---------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("feat: add widget", "add widget"),
    ("fix(api): handle nulls", "handle nulls"),
    ("CHORE: bump deps", "bump deps"),
    ("Refactor(core): tidy up", "tidy up"),
    ("revert: undo that", "undo that"),
])
def test_strip_conventional_prefix_removes_known_prefixes(ga, title, expected):
    assert ga.parsing.strip_conventional_prefix(title) == expected


@pytest.mark.parametrize("title", [
    "Add widget",                 # no prefix at all
    "features: not conventional", # not in the allowed set
    "wip: also not in the set",
    "later feat: mid-string",     # only anchored prefixes are stripped
])
def test_strip_conventional_prefix_leaves_other_titles_alone(ga, title):
    assert ga.parsing.strip_conventional_prefix(title) == title


def test_strip_conventional_prefix_strips_only_the_outermost_prefix(ga):
    assert ga.parsing.strip_conventional_prefix("feat: fix: double") == "fix: double"


# --- extract_ticket_refs ---------------------------------------------------

def test_extract_ticket_refs_finds_all_occurrences_in_order(ga):
    assert ga.parsing.extract_ticket_refs("closes #101, see also #7 and #101") == [101, 7, 101]


@pytest.mark.parametrize("text", [None, "", "no refs here", "#notanumber"])
def test_extract_ticket_refs_returns_empty_when_nothing_matches(ga, text):
    assert ga.parsing.extract_ticket_refs(text) == []


def test_extract_ticket_refs_reads_digits_glued_to_words(ga):
    # documents current behaviour: the regex is not word-boundary anchored
    assert ga.parsing.extract_ticket_refs("PR#42") == [42]
