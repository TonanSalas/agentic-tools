"""Per-repo activity gathering across the six GitHub activity sources."""

import json
import subprocess
import sys
from collections import defaultdict

from . import dates, gh, parsing
from .config import GIT_AUTHOR, GH_USERNAME


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
    """
    # (repo, ticket_number) -> per-day info
    activity = defaultdict(lambda: defaultdict(lambda: {"title": "", "sources": set()}))
    pr_numbers = set()

    def key(num):
        return (repo, num)

    # --- 1. Commits by author ---
    commits = gh.gh_api(f"repos/{repo}/commits", {
        "author": GIT_AUTHOR,
        "since": f"{api_since}T00:00:00Z",
        "until": f"{api_until}T00:00:00Z",
        "per_page": "100"
    })
    for c in commits:
        day = dates.parse_date(c.get("commit", {}).get("author", {}).get("date", ""))
        if not dates.date_in_range(day, start, end):
            continue
        msg = c.get("commit", {}).get("message", "").split("\n")[0]
        for ticket_num in parsing.extract_ticket_refs(msg):
            activity[day][key(ticket_num)]["sources"].add("commits")

    # --- 2. PRs authored ---
    # Search with wider window (api dates) since GitHub search uses UTC
    prs = gh.gh_search(repo, "pr", [f"--search=created:>={api_since} created:<={api_until}"])
    for pr in prs:
        day = dates.parse_date(pr.get("createdAt"))
        if not dates.date_in_range(day, start, end):
            continue
        num = pr["number"]
        title = parsing.strip_conventional_prefix(pr.get("title", ""))
        pr_numbers.add(num)
        activity[day][key(num)]["title"] = title
        activity[day][key(num)]["sources"].add("authored-pr")
        merge_day = dates.parse_date(pr.get("mergedAt"))
        if merge_day and dates.date_in_range(merge_day, start, end) and merge_day != day:
            activity[merge_day][key(num)]["title"] = title
            activity[merge_day][key(num)]["sources"].add("authored-pr")
        for ref in parsing.extract_ticket_refs(pr.get("body", "")):
            activity[day][key(ref)]["sources"].add("pr-ref")

    # --- 3. Issue comments ---
    issue_comments = gh.gh_api(f"repos/{repo}/issues/comments", {
        "since": f"{api_since}T00:00:00Z",
        "per_page": "100"
    })
    issue_comment_numbers = set()
    for ic in issue_comments:
        if ic.get("user", {}).get("login") != GH_USERNAME:
            continue
        day = dates.parse_date(ic.get("created_at"))
        if not dates.date_in_range(day, start, end):
            continue
        issue_num = int(ic.get("issue_url", "").split("/")[-1])
        issue_comment_numbers.add(issue_num)
        activity[day][key(issue_num)]["sources"].add("issue-comment")

    # --- 4. PR review comments (inline) ---
    pr_review_comments = gh.gh_api(f"repos/{repo}/pulls/comments", {
        "since": f"{api_since}T00:00:00Z",
        "per_page": "100"
    })
    pr_comment_numbers = set()
    for rc in pr_review_comments:
        if rc.get("user", {}).get("login") != GH_USERNAME:
            continue
        day = dates.parse_date(rc.get("created_at"))
        if not dates.date_in_range(day, start, end):
            continue
        pr_num = int(rc.get("pull_request_url", "").split("/")[-1])
        pr_comment_numbers.add(pr_num)
        activity[day][key(pr_num)]["sources"].add("review-comment")

    # --- 5. PR reviews (approve/request-changes/comment) ---
    review_pr_numbers = set()
    result = subprocess.run(
        ["gh", "pr", "list", "--repo", repo, "--state=all",
         f"--search=reviewed-by:{GH_USERNAME} updated:>={api_since} updated:<={api_until}",
         "--json", "number,title,createdAt,mergedAt,body", "--limit", "100"],
        capture_output=True, text=True
    )
    reviewed_prs = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else []
    for pr in reviewed_prs:
        pr_num = pr["number"]
        reviews = gh.gh_api(f"repos/{repo}/pulls/{pr_num}/reviews", paginate=False)
        for rev in (reviews if isinstance(reviews, list) else []):
            if rev.get("user", {}).get("login") != GH_USERNAME:
                continue
            day = dates.parse_date(rev.get("submitted_at"))
            if dates.date_in_range(day, start, end):
                review_pr_numbers.add(pr_num)
                title = parsing.strip_conventional_prefix(pr.get("title", ""))
                activity[day][key(pr_num)]["title"] = title
                activity[day][key(pr_num)]["sources"].add("pr-review")

    # --- 6. Issues authored ---
    issues = gh.gh_search(repo, "issue", [f"--search=created:>={api_since} created:<={api_until}"])
    for issue in issues:
        day = dates.parse_date(issue.get("createdAt"))
        if not dates.date_in_range(day, start, end):
            continue
        num = issue["number"]
        title = parsing.strip_conventional_prefix(issue.get("title", ""))
        activity[day][key(num)]["title"] = title
        activity[day][key(num)]["sources"].add("authored-issue")

    # --- Collect all referenced (repo, number) keys ---
    all_keys = set()
    for day_data in activity.values():
        all_keys.update(day_data.keys())

    # --- Fetch metadata (title + state) for every ticket via one API call each ---
    meta_by_key = {}
    for k in all_keys:
        meta = gh.fetch_item_meta(k[0], k[1])
        meta["title"] = parsing.strip_conventional_prefix(meta["title"])
        meta_by_key[k] = meta

    # --- Backfill titles into per-day activity ---
    for day_data in activity.values():
        for k, info in day_data.items():
            if not info["title"] and k in meta_by_key:
                info["title"] = meta_by_key[k]["title"]

    return activity, pr_numbers, pr_comment_numbers, review_pr_numbers, prs, meta_by_key

