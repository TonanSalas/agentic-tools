"""Per-repo activity gathering across the six GitHub activity sources.

Each source is its own collector. They all take the same `Window` and write
into a shared `activity` accumulator, so they can be tested one at a time
without driving the whole repo gather.
"""

import json
import subprocess
from collections import defaultdict
from typing import NamedTuple

from . import dates, gh, parsing
from .config import GIT_AUTHOR, GH_USERNAME


class Window(NamedTuple):
    """One repo plus the two date ranges a gather runs against.

    `start`/`end` are the local dates results are filtered to; `api_since`/
    `api_until` are the wider UTC window used for the API queries, so items
    near a boundary aren't missed to timezone skew.
    """

    repo: str
    start: str
    end: str
    api_since: str
    api_until: str


def new_accumulator():
    """day -> (repo, number) -> {"title": str, "sources": set}."""
    return defaultdict(lambda: defaultdict(lambda: {"title": "", "sources": set()}))


def _mark(acc, day, repo, num, source, title=None):
    entry = acc[day][(repo, num)]
    entry["sources"].add(source)
    if title:
        entry["title"] = title


def collect_commits(w, acc):
    """Commits authored in the window; credits any #refs in the subject line."""
    commits = gh.gh_api(f"repos/{w.repo}/commits", {
        "author": GIT_AUTHOR,
        "since": f"{w.api_since}T00:00:00Z",
        "until": f"{w.api_until}T00:00:00Z",
        "per_page": "100"
    })
    for c in commits:
        day = dates.parse_date(c.get("commit", {}).get("author", {}).get("date", ""))
        if not dates.date_in_range(day, w.start, w.end):
            continue
        msg = c.get("commit", {}).get("message", "").split("\n")[0]
        for ticket_num in parsing.extract_ticket_refs(msg):
            _mark(acc, day, w.repo, ticket_num, "commits")


def collect_authored_prs(w, acc):
    """PRs the user opened. Returns (pr_numbers, prs) for merge counting.

    A PR merged on a different day inside the range is recorded on both its
    creation day and its merge day.
    """
    # Search with wider window (api dates) since GitHub search uses UTC
    prs = gh.gh_search(w.repo, "pr", [f"--search=created:>={w.api_since} created:<={w.api_until}"])
    pr_numbers = set()
    for pr in prs:
        day = dates.parse_date(pr.get("createdAt"))
        if not dates.date_in_range(day, w.start, w.end):
            continue
        num = pr["number"]
        title = parsing.strip_conventional_prefix(pr.get("title", ""))
        pr_numbers.add(num)
        _mark(acc, day, w.repo, num, "authored-pr", title)
        merge_day = dates.parse_date(pr.get("mergedAt"))
        if merge_day and dates.date_in_range(merge_day, w.start, w.end) and merge_day != day:
            _mark(acc, merge_day, w.repo, num, "authored-pr", title)
        for ref in parsing.extract_ticket_refs(pr.get("body", "")):
            _mark(acc, day, w.repo, ref, "pr-ref")
    return pr_numbers, prs


def collect_issue_comments(w, acc):
    """Comments the user left on issues (and on PRs, via the issues endpoint)."""
    issue_comments = gh.gh_api(f"repos/{w.repo}/issues/comments", {
        "since": f"{w.api_since}T00:00:00Z",
        "per_page": "100"
    })
    for ic in issue_comments:
        if ic.get("user", {}).get("login") != GH_USERNAME:
            continue
        day = dates.parse_date(ic.get("created_at"))
        if not dates.date_in_range(day, w.start, w.end):
            continue
        issue_num = int(ic.get("issue_url", "").split("/")[-1])
        _mark(acc, day, w.repo, issue_num, "issue-comment")


def collect_review_comments(w, acc):
    """Inline review comments the user left on PRs. Returns the PR numbers."""
    pr_review_comments = gh.gh_api(f"repos/{w.repo}/pulls/comments", {
        "since": f"{w.api_since}T00:00:00Z",
        "per_page": "100"
    })
    pr_comment_numbers = set()
    for rc in pr_review_comments:
        if rc.get("user", {}).get("login") != GH_USERNAME:
            continue
        day = dates.parse_date(rc.get("created_at"))
        if not dates.date_in_range(day, w.start, w.end):
            continue
        pr_num = int(rc.get("pull_request_url", "").split("/")[-1])
        pr_comment_numbers.add(pr_num)
        _mark(acc, day, w.repo, pr_num, "review-comment")
    return pr_comment_numbers


def collect_reviews(w, acc):
    """PR reviews (approve / request-changes / comment). Returns the PR numbers.

    This is the one source with no `gh api` equivalent -- `reviewed-by:` is a
    search qualifier, so it shells out to `gh pr list` directly.
    """
    review_pr_numbers = set()
    result = subprocess.run(
        ["gh", "pr", "list", "--repo", w.repo, "--state=all",
         f"--search=reviewed-by:{GH_USERNAME} updated:>={w.api_since} updated:<={w.api_until}",
         "--json", "number,title,createdAt,mergedAt,body", "--limit", "100"],
        capture_output=True, text=True
    )
    reviewed_prs = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else []
    for pr in reviewed_prs:
        pr_num = pr["number"]
        reviews = gh.gh_api(f"repos/{w.repo}/pulls/{pr_num}/reviews", paginate=False)
        for rev in (reviews if isinstance(reviews, list) else []):
            if rev.get("user", {}).get("login") != GH_USERNAME:
                continue
            day = dates.parse_date(rev.get("submitted_at"))
            if dates.date_in_range(day, w.start, w.end):
                review_pr_numbers.add(pr_num)
                title = parsing.strip_conventional_prefix(pr.get("title", ""))
                _mark(acc, day, w.repo, pr_num, "pr-review", title)
    return review_pr_numbers


def collect_authored_issues(w, acc):
    """Issues the user opened in the window."""
    issues = gh.gh_search(w.repo, "issue", [f"--search=created:>={w.api_since} created:<={w.api_until}"])
    for issue in issues:
        day = dates.parse_date(issue.get("createdAt"))
        if not dates.date_in_range(day, w.start, w.end):
            continue
        num = issue["number"]
        title = parsing.strip_conventional_prefix(issue.get("title", ""))
        _mark(acc, day, w.repo, num, "authored-issue", title)


def fetch_metadata(acc):
    """One metadata call per referenced ticket. Returns (repo, number) -> meta."""
    all_keys = set()
    for day_data in acc.values():
        all_keys.update(day_data.keys())

    meta_by_key = {}
    for k in all_keys:
        meta = gh.fetch_item_meta(k[0], k[1])
        meta["title"] = parsing.strip_conventional_prefix(meta["title"])
        meta_by_key[k] = meta
    return meta_by_key


def backfill_titles(acc, meta_by_key):
    """Give every entry that a collector left untitled its fetched title."""
    for day_data in acc.values():
        for k, info in day_data.items():
            if not info["title"] and k in meta_by_key:
                info["title"] = meta_by_key[k]["title"]


def gather_repo_activity(repo, start, end, api_since, api_until):
    """
    Gather all activity for a single repo.

    Args:
        repo: full repo name (org/repo)
        start, end: local date range (YYYY-MM-DD) for filtering
        api_since, api_until: UTC date strings for API queries (wider window to
            account for timezone offset)

    Returns:
        activity: dict[day_str] -> dict[(repo, number)] -> {"title": str, "sources": set}
        pr_numbers: set of PR numbers authored
        pr_comment_numbers: set of PR numbers with review comments
        review_pr_numbers: set of PR numbers with reviews
        prs: list of authored PR dicts (for merge counting)
        meta_by_key: (repo, number) -> issue/PR metadata
    """
    w = Window(repo, start, end, api_since, api_until)
    activity = new_accumulator()

    collect_commits(w, activity)
    pr_numbers, prs = collect_authored_prs(w, activity)
    collect_issue_comments(w, activity)
    pr_comment_numbers = collect_review_comments(w, activity)
    review_pr_numbers = collect_reviews(w, activity)
    collect_authored_issues(w, activity)

    meta_by_key = fetch_metadata(activity)
    backfill_titles(activity, meta_by_key)

    return activity, pr_numbers, pr_comment_numbers, review_pr_numbers, prs, meta_by_key
