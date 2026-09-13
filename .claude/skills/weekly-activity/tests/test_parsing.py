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


# --- extract_ticket_refs: things that look like refs but aren't -------------

@pytest.mark.parametrize("text,expected", [
    # A CSS hex colour. `\d+` alone matches "662" and stops at the "C",
    # which is how insurance_portal#60 minted a phantom ticket #662.
    ("`#662CBE` is sampled from the capture's own screenshot", []),
    ("#12ab", []),
    ("#0f0", []),
    ("#deadbeef", []),
])
def test_extract_ticket_refs_ignores_digits_followed_by_letters(ga, text, expected):
    assert ga.parsing.extract_ticket_refs(text) == expected


def test_extract_ticket_refs_still_reads_refs_next_to_punctuation(ga):
    assert ga.parsing.extract_ticket_refs("Fixes #1234, closes #56. See (#7)") == [1234, 56, 7]
