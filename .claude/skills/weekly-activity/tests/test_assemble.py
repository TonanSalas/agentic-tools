"""Cross-repo assembly: window widening, dedup, per-day view."""

import pytest

START, END = "2026-04-06", "2026-04-10"
API_SINCE, API_UNTIL = "2026-04-05", "2026-04-12"


def test_gather_all_returns_an_empty_shape_when_no_repos_are_active(ga, monkeypatch):
    monkeypatch.setattr(ga.discovery, "discover_repos", lambda *a: [])
    data = ga.assemble.gather_all(START, END)
    assert (data["start"], data["end"]) == (START, END)
    assert data["repos"] == [] and data["days"] == {} and data["tickets"] == []
    assert data["generated_at"]


def test_gather_all_widens_the_api_window_around_the_local_range(ga, monkeypatch):
    seen = {}

    def fake_discover(since, until):
        seen["window"] = (since, until)
        return []

    monkeypatch.setattr(ga.discovery, "discover_repos", fake_discover)
    ga.assemble.gather_all(START, END)
    # one day back, two days forward, to absorb the UTC offset
    assert seen["window"] == (API_SINCE, API_UNTIL)


@pytest.fixture
def two_repo_data(ga, monkeypatch):
    def canned(repo, start, end, api_since, api_until):
        short = repo.split("/")[-1]
        if short == "alpha":
            activity = {
                "2026-04-06": {(repo, 55): {"title": "add widget", "sources": {"authored-pr"}}},
                "2026-04-07": {(repo, 55): {"title": "", "sources": {"commits"}}},
            }
            meta = {(repo, 55): {"title": "add widget", "state": "closed",
                                 "state_reason": None, "is_pr": True, "merged": True}}
        else:
            activity = {
                "2026-04-07": {(repo, 9): {"title": "beta thing", "sources": {"authored-issue"}}},
            }
            meta = {(repo, 9): {"title": "beta thing", "state": "open",
                                "state_reason": None, "is_pr": False, "merged": None}}
        return activity, set(), set(), set(), [], meta

    monkeypatch.setattr(ga.discovery, "discover_repos",
                        lambda *a: ["dragonflyic/alpha", "dragonflyic/beta"])
    monkeypatch.setattr(ga.collect, "gather_repo_activity", canned)
    return ga.assemble.gather_all(START, END)


def test_gather_all_lists_short_repo_names(ga, two_repo_data):
    assert two_repo_data["repos"] == ["alpha", "beta"]


def test_gather_all_dedups_a_ticket_across_days_and_unions_its_sources(ga, two_repo_data):
    ticket = next(t for t in two_repo_data["tickets"] if t["number"] == 55)
    assert ticket["days"] == ["2026-04-06", "2026-04-07"]
    assert ticket["sources"] == ["authored-pr", "commits"]
    assert (ticket["repo"], ticket["is_pr"], ticket["merged"]) == ("alpha", True, True)


def test_gather_all_keeps_tickets_from_every_repo(ga, two_repo_data):
    assert {(t["repo"], t["number"]) for t in two_repo_data["tickets"]} == {
        ("alpha", 55), ("beta", 9),
    }


def test_gather_all_builds_a_per_day_view(ga, two_repo_data):
    days = two_repo_data["days"]
    assert sorted(days) == ["2026-04-06", "2026-04-07"]
    assert [it["number"] for it in days["2026-04-07"]] == [55, 9]


def test_per_day_items_inherit_missing_titles_from_the_ticket_index(ga, two_repo_data):
    item = next(it for it in two_repo_data["days"]["2026-04-07"] if it["number"] == 55)
    assert item["title"] == "add widget"
    assert item["sources"] == ["commits"]   # per-day sources stay day-specific


# --- unresolvable references ------------------------------------------------
#
# `collect_authored_prs` scrapes #refs out of free-form PR bodies, so a number
# that is not a ticket at all can enter the accumulator -- a Chubb quote id
# ("quote #4970877") did exactly that. A reference GitHub reports as missing is
# dropped; one we merely failed to reach is kept, because dropping it would
# silently lose real work.

@pytest.fixture
def data_with_unresolved_refs(ga, monkeypatch):
    def canned(repo, start, end, api_since, api_until):
        activity = {
            "2026-04-06": {
                (repo, 55): {"title": "add widget", "sources": {"authored-pr"}},
                (repo, 4970877): {"title": "", "sources": {"pr-ref"}},
                (repo, 777): {"title": "", "sources": {"pr-ref"}},
            },
        }
        meta = {
            (repo, 55): {"title": "add widget", "state": "closed", "state_reason": None,
                         "is_pr": True, "merged": True, "resolution": "ok"},
            (repo, 4970877): {"title": "(unknown #4970877)", "state": "unknown",
                              "state_reason": None, "is_pr": False, "merged": None,
                              "resolution": "missing"},
            (repo, 777): {"title": "(unknown #777)", "state": "unknown",
                          "state_reason": None, "is_pr": False, "merged": None,
                          "resolution": "unavailable"},
        }
        return activity, set(), set(), set(), [], meta

    monkeypatch.setattr(ga.discovery, "discover_repos", lambda *a: ["dragonflyic/alpha"])
    monkeypatch.setattr(ga.collect, "gather_repo_activity", canned)
    return ga.assemble.gather_all(START, END)


def test_gather_all_drops_references_github_reports_as_missing(ga, data_with_unresolved_refs):
    assert 4970877 not in {t["number"] for t in data_with_unresolved_refs["tickets"]}


def test_gather_all_drops_missing_references_from_the_per_day_view_too(ga, data_with_unresolved_refs):
    assert 4970877 not in {it["number"] for it in data_with_unresolved_refs["days"]["2026-04-06"]}


def test_gather_all_keeps_references_it_merely_could_not_reach(ga, data_with_unresolved_refs):
    # unreachable != nonexistent; dropping these would lose real work silently
    assert 777 in {t["number"] for t in data_with_unresolved_refs["tickets"]}


def test_gather_all_keeps_real_tickets_when_dropping_missing_ones(ga, data_with_unresolved_refs):
    assert 55 in {t["number"] for t in data_with_unresolved_refs["tickets"]}
