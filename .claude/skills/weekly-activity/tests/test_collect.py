"""Per-repo collection across the six activity sources."""

import json

import pytest

START, END = "2026-04-06", "2026-04-10"
API_SINCE, API_UNTIL = "2026-04-05", "2026-04-12"


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
                {"user": {"login": ga.config.GH_USERNAME},
                 "created_at": "2026-04-07T12:00:00Z",
                 "issue_url": f"https://api.github.com/repos/{REPO}/issues/101"},
                {"user": {"login": "someone-else"},
                 "created_at": "2026-04-07T12:00:00Z",
                 "issue_url": f"https://api.github.com/repos/{REPO}/issues/222"},
            ]
        if endpoint == f"repos/{REPO}/pulls/comments":
            return [
                {"user": {"login": ga.config.GH_USERNAME},
                 "created_at": "2026-04-10T12:00:00Z",
                 "pull_request_url": f"https://api.github.com/repos/{REPO}/pulls/77"},
            ]
        if endpoint == f"repos/{REPO}/pulls/77/reviews":
            return [
                {"user": {"login": ga.config.GH_USERNAME}, "submitted_at": "2026-04-10T12:00:00Z"},
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

    monkeypatch.setattr(ga.gh, "gh_api", fake_gh_api)
    monkeypatch.setattr(ga.gh, "gh_search", fake_gh_search)
    monkeypatch.setattr(ga.gh, "fetch_item_meta", fake_fetch_item_meta)
    # the reviewed-by PR list is the one call that shells out directly
    monkeypatch.setattr(ga.collect.subprocess, "run", lambda cmd, **k: completed(
        stdout=json.dumps([{"number": 77, "title": "fix: their bug",
                            "createdAt": "2026-04-02T12:00:00Z",
                            "mergedAt": None, "body": ""}])))

    return ga.collect.gather_repo_activity(REPO, START, END, API_SINCE, API_UNTIL)


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


# --- PR merge-window edge cases -------------------------------------------

@pytest.fixture
def only_prs(ga, monkeypatch, completed):
    """Wire a repo whose only activity is one authored PR, described per-test."""
    def _wire(pr):
        monkeypatch.setattr(ga.gh, "gh_api", lambda *a, **k: [])
        monkeypatch.setattr(ga.gh, "gh_search",
                            lambda repo, resource, parts: [pr] if resource == "pr" else [])
        monkeypatch.setattr(ga.gh, "fetch_item_meta", lambda repo, number: {
            "title": pr["title"], "state": "open", "state_reason": None,
            "is_pr": True, "merged": bool(pr.get("mergedAt"))})
        monkeypatch.setattr(ga.collect.subprocess, "run", lambda cmd, **k: completed(stdout="[]"))
        activity, *_ = ga.collect.gather_repo_activity(REPO, START, END, API_SINCE, API_UNTIL)
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
