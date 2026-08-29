"""Repo discovery and per-repo / cross-repo activity aggregation."""

import json

import pytest

START, END = "2026-04-06", "2026-04-10"
API_SINCE, API_UNTIL = "2026-04-05", "2026-04-12"


def event(day, repo, hour="12:00:00"):
    return {"created_at": f"{day}T{hour}Z", "repo": {"name": repo}}


# --- discover_repos --------------------------------------------------------

def test_discover_repos_collects_in_range_org_repos(ga, monkeypatch):
    monkeypatch.setattr(ga, "gh_api", lambda *a, **k: [
        event("2026-04-10", "dragonflyic/gamma"),
        event("2026-04-08", "dragonflyic/alpha"),
        event("2026-04-08", "dragonflyic/alpha"),  # duplicate collapses
    ])
    assert ga.discover_repos(START, END) == ["dragonflyic/alpha", "dragonflyic/gamma"]


def test_discover_repos_ignores_other_orgs(ga, monkeypatch):
    monkeypatch.setattr(ga, "gh_api", lambda *a, **k: [
        event("2026-04-08", "someoneelse/beta"),
        event("2026-04-08", "dragonflyic/alpha"),
    ])
    assert ga.discover_repos(START, END) == ["dragonflyic/alpha"]


def test_discover_repos_skips_events_after_the_range(ga, monkeypatch):
    monkeypatch.setattr(ga, "gh_api", lambda *a, **k: [
        event("2026-04-20", "dragonflyic/future"),   # newer than END: skipped, not fatal
        event("2026-04-08", "dragonflyic/alpha"),
    ])
    assert ga.discover_repos(START, END) == ["dragonflyic/alpha"]


def test_discover_repos_stops_at_the_first_event_before_the_range(ga, monkeypatch):
    # The Events API is newest-first, so the walk short-circuits. Anything after
    # an out-of-range event is never seen, even if it would have matched.
    monkeypatch.setattr(ga, "gh_api", lambda *a, **k: [
        event("2026-04-08", "dragonflyic/alpha"),
        event("2026-04-01", "dragonflyic/old"),
        event("2026-04-09", "dragonflyic/unreachable"),
    ])
    assert ga.discover_repos(START, END) == ["dragonflyic/alpha"]


def test_discover_repos_queries_the_users_event_feed(ga, monkeypatch):
    seen = {}

    def fake_gh_api(endpoint, params=None, **k):
        seen["endpoint"] = endpoint
        seen["params"] = params
        return []

    monkeypatch.setattr(ga, "gh_api", fake_gh_api)
    assert ga.discover_repos(START, END) == []
    assert seen["endpoint"] == f"users/{ga.GH_USERNAME}/events"
    assert seen["params"] == {"per_page": "100"}


# --- gather_repo_activity --------------------------------------------------

REPO = "dragonflyic/alpha"


@pytest.fixture
def wired_repo(ga, monkeypatch, completed):
    """Wire every outbound call gather_repo_activity makes with realistic fixtures."""
    def fake_gh_api(endpoint, params=None, paginate=True):
        if endpoint == f"repos/{REPO}/commits":
            return [
                {"commit": {"author": {"date": "2026-04-07T12:00:00Z"},
                            "message": "feat: work on #101\n\nbody"}},
                {"commit": {"author": {"date": "2026-04-01T12:00:00Z"},
                            "message": "chore: out of range #999"}},
            ]
        if endpoint == f"repos/{REPO}/issues/comments":
            return [
                {"user": {"login": ga.GH_USERNAME},
                 "created_at": "2026-04-07T12:00:00Z",
                 "issue_url": f"https://api.github.com/repos/{REPO}/issues/101"},
                {"user": {"login": "someone-else"},
                 "created_at": "2026-04-07T12:00:00Z",
                 "issue_url": f"https://api.github.com/repos/{REPO}/issues/222"},
            ]
        if endpoint == f"repos/{REPO}/pulls/comments":
            return [
                {"user": {"login": ga.GH_USERNAME},
                 "created_at": "2026-04-10T12:00:00Z",
                 "pull_request_url": f"https://api.github.com/repos/{REPO}/pulls/77"},
            ]
        if endpoint == f"repos/{REPO}/pulls/77/reviews":
            return [
                {"user": {"login": ga.GH_USERNAME}, "submitted_at": "2026-04-10T12:00:00Z"},
                {"user": {"login": "someone-else"}, "submitted_at": "2026-04-10T12:00:00Z"},
            ]
        return []

    def fake_gh_search(repo, resource, query_parts):
        if resource == "pr":
            return [{"number": 55, "title": "feat(api): add widget",
                     "createdAt": "2026-04-08T12:00:00Z",
                     "mergedAt": "2026-04-09T15:00:00Z",
                     "body": "closes #101"}]
        return [{"number": 101, "title": "chore: the epic",
                 "createdAt": "2026-04-06T12:00:00Z"}]

    titles = {55: "feat(api): add widget", 77: "fix: their bug", 101: "chore: the epic"}

    def fake_fetch_item_meta(repo, number):
        return {"title": titles.get(number, f"(unknown #{number})"),
                "state": "open", "state_reason": None,
                "is_pr": number in (55, 77), "merged": number == 55}

    monkeypatch.setattr(ga, "gh_api", fake_gh_api)
    monkeypatch.setattr(ga, "gh_search", fake_gh_search)
    monkeypatch.setattr(ga, "fetch_item_meta", fake_fetch_item_meta)
    # the reviewed-by PR list is the one call that shells out directly
    monkeypatch.setattr(ga.subprocess, "run", lambda cmd, **k: completed(
        stdout=json.dumps([{"number": 77, "title": "fix: their bug",
                            "createdAt": "2026-04-02T12:00:00Z",
                            "mergedAt": None, "body": ""}])))

    return ga.gather_repo_activity(REPO, START, END, API_SINCE, API_UNTIL)


def sources(activity, day, num):
    return activity[day][(REPO, num)]["sources"]


def test_commit_ticket_refs_land_on_the_commit_day(ga, wired_repo):
    activity = wired_repo[0]
    assert "commits" in sources(activity, "2026-04-07", 101)


def test_out_of_range_commits_are_dropped(ga, wired_repo):
    activity = wired_repo[0]
    assert "2026-04-01" not in activity
    assert all((REPO, 999) not in day for day in activity.values())


def test_authored_pr_is_recorded_with_a_stripped_title(ga, wired_repo):
    activity = wired_repo[0]
    entry = activity["2026-04-08"][(REPO, 55)]
    assert entry["title"] == "add widget"
    assert "authored-pr" in entry["sources"]


def test_authored_pr_also_appears_on_its_merge_day(ga, wired_repo):
    activity = wired_repo[0]
    assert "authored-pr" in sources(activity, "2026-04-09", 55)
    assert activity["2026-04-09"][(REPO, 55)]["title"] == "add widget"


def test_tickets_referenced_from_a_pr_body_are_credited(ga, wired_repo):
    activity = wired_repo[0]
    assert "pr-ref" in sources(activity, "2026-04-08", 101)


def test_issue_comments_by_other_users_are_ignored(ga, wired_repo):
    activity = wired_repo[0]
    assert "issue-comment" in sources(activity, "2026-04-07", 101)
    assert all((REPO, 222) not in day for day in activity.values())


def test_inline_review_comments_are_attributed_to_their_pr(ga, wired_repo):
    activity = wired_repo[0]
    assert "review-comment" in sources(activity, "2026-04-10", 77)


def test_pr_reviews_are_recorded_with_the_reviewed_prs_title(ga, wired_repo):
    activity = wired_repo[0]
    entry = activity["2026-04-10"][(REPO, 77)]
    assert "pr-review" in entry["sources"]
    assert entry["title"] == "their bug"


def test_authored_issues_are_recorded(ga, wired_repo):
    activity = wired_repo[0]
    assert "authored-issue" in sources(activity, "2026-04-06", 101)


def test_titles_are_backfilled_onto_days_that_had_none(ga, wired_repo):
    activity = wired_repo[0]
    # #101 on 04-07 came only from a commit ref, so its title came from metadata
    assert activity["2026-04-07"][(REPO, 101)]["title"] == "the epic"


def test_gather_repo_activity_reports_the_number_sets(ga, wired_repo):
    _activity, pr_numbers, pr_comment_numbers, review_pr_numbers, prs, meta = wired_repo
    assert pr_numbers == {55}
    assert pr_comment_numbers == {77}
    assert review_pr_numbers == {77}
    assert [p["number"] for p in prs] == [55]
    assert set(meta) == {(REPO, 55), (REPO, 77), (REPO, 101)}


def test_metadata_titles_are_prefix_stripped(ga, wired_repo):
    meta = wired_repo[5]
    assert meta[(REPO, 55)]["title"] == "add widget"


# --- gather_all ------------------------------------------------------------

def test_gather_all_returns_an_empty_shape_when_no_repos_are_active(ga, monkeypatch):
    monkeypatch.setattr(ga, "discover_repos", lambda *a: [])
    data = ga.gather_all(START, END)
    assert (data["start"], data["end"]) == (START, END)
    assert data["repos"] == [] and data["days"] == {} and data["tickets"] == []
    assert data["generated_at"]


def test_gather_all_widens_the_api_window_around_the_local_range(ga, monkeypatch):
    seen = {}

    def fake_discover(since, until):
        seen["window"] = (since, until)
        return []

    monkeypatch.setattr(ga, "discover_repos", fake_discover)
    ga.gather_all(START, END)
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

    monkeypatch.setattr(ga, "discover_repos",
                        lambda *a: ["dragonflyic/alpha", "dragonflyic/beta"])
    monkeypatch.setattr(ga, "gather_repo_activity", canned)
    return ga.gather_all(START, END)


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


# --- PR merge-window edge cases -------------------------------------------

@pytest.fixture
def only_prs(ga, monkeypatch, completed):
    """Wire a repo whose only activity is one authored PR, described per-test."""
    def _wire(pr):
        monkeypatch.setattr(ga, "gh_api", lambda *a, **k: [])
        monkeypatch.setattr(ga, "gh_search",
                            lambda repo, resource, parts: [pr] if resource == "pr" else [])
        monkeypatch.setattr(ga, "fetch_item_meta", lambda repo, number: {
            "title": pr["title"], "state": "open", "state_reason": None,
            "is_pr": True, "merged": bool(pr.get("mergedAt"))})
        monkeypatch.setattr(ga.subprocess, "run", lambda cmd, **k: completed(stdout="[]"))
        activity, *_ = ga.gather_repo_activity(REPO, START, END, API_SINCE, API_UNTIL)
        return {day: set(data[(REPO, pr["number"])]["sources"])
                for day, data in activity.items() if (REPO, pr["number"]) in data}
    return _wire


def test_pr_created_and_merged_the_same_day_is_recorded_once(ga, only_prs):
    days = only_prs({"number": 55, "title": "add widget", "body": "",
                     "createdAt": "2026-04-08T12:00:00Z",
                     "mergedAt": "2026-04-08T18:00:00Z"})
    assert days == {"2026-04-08": {"authored-pr"}}


def test_open_pr_is_recorded_on_its_creation_day_only(ga, only_prs):
    days = only_prs({"number": 55, "title": "add widget", "body": "",
                     "createdAt": "2026-04-08T12:00:00Z", "mergedAt": None})
    assert days == {"2026-04-08": {"authored-pr"}}


def test_merge_after_the_range_is_not_recorded(ga, only_prs):
    # the API window reaches past END, so a later merge can come back — and must be dropped
    days = only_prs({"number": 55, "title": "add widget", "body": "",
                     "createdAt": "2026-04-08T12:00:00Z",
                     "mergedAt": "2026-04-12T12:00:00Z"})
    assert days == {"2026-04-08": {"authored-pr"}}


def test_pr_created_before_the_range_is_dropped_even_if_merged_inside_it(ga, only_prs):
    # documents current behaviour: filtering happens on the creation day, so the
    # in-range merge of an older PR never lands in the report
    days = only_prs({"number": 55, "title": "add widget", "body": "",
                     "createdAt": "2026-04-05T12:00:00Z",
                     "mergedAt": "2026-04-08T12:00:00Z"})
    assert days == {}
