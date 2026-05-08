#!/usr/bin/env python3
"""
Gather GitHub activity for a user across all repos in an org for a date range.

Uses the Events API to discover which repos had activity, then collects
per-repo: commits, authored PRs, issue comments, PR review comments,
PR reviews, and authored issues.

Outputs a markdown table grouped by day.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ORG = "dragonflyic"
GH_USERNAME = "tonansalas-dragonfly"
GIT_AUTHOR = "tonansalas"
LOCAL_TZ = timezone(timedelta(hours=-5))  # CDT (US Central Daylight)

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def gh_api(endpoint, params=None, paginate=True):
    """Call gh api and return parsed JSON."""
    cmd = ["gh", "api", endpoint, "--method", "GET"]
    for k, v in (params or {}).items():
        cmd += ["-f", f"{k}={v}"]
    if paginate:
        cmd.append("--paginate")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Warning: gh api {endpoint} failed: {result.stderr}", file=sys.stderr)
        return []
    raw = result.stdout.strip()
    if not raw:
        return []
    # Fix paginated output: "][" -> ","
    raw = raw.replace("]\n[", ",").replace("][", ",")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"Warning: failed to parse JSON from {endpoint}", file=sys.stderr)
        return []


def gh_search(repo, resource, query_parts):
    """Use gh list commands for searching PRs/issues."""
    json_fields = "number,title,createdAt,mergedAt,body" if resource == "pr" else "number,title,createdAt"
    cmd = ["gh", resource, "list", "--repo", repo,
           f"--author={GH_USERNAME}", "--state=all",
           "--json", json_fields, "--limit", "100"]
    for part in query_parts:
        cmd.append(part)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Warning: gh {resource} list failed: {result.stderr}", file=sys.stderr)
        return []
    try:
        return json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return []


def parse_date(iso_str):
    """Convert a UTC ISO timestamp to a local-timezone YYYY-MM-DD date."""
    if not iso_str:
        return None
    try:
        # Handle both "2026-04-04T03:48:35Z" and "2026-04-04T03:48:35+00:00"
        cleaned = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned).astimezone(LOCAL_TZ)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso_str[:10]


def date_in_range(date_str, start, end):
    """Check if a YYYY-MM-DD string falls within [start, end]."""
    if not date_str:
        return False
    return start <= date_str <= end


def fetch_item_title(repo, number):
    """Fetch issue/PR title by number."""
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{number}", "--jq", ".title"],
        capture_output=True, text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return f"(unknown #{number})"


def strip_conventional_prefix(title):
    """Remove conventional commit prefixes like feat:, fix(scope):, etc."""
    return re.sub(r"^(feat|fix|chore|docs|refactor|test|ci|build|perf|style|revert)(\([^)]*\))?:\s*", "", title, flags=re.IGNORECASE)


def extract_ticket_refs(text):
    """Extract ticket numbers from text (#NNN patterns)."""
    if not text:
        return []
    return [int(m) for m in re.findall(r"#(\d+)", text)]


# ---------------------------------------------------------------------------
# Repo discovery via Events API
# ---------------------------------------------------------------------------

def discover_repos(start, end):
    """Use the Events API to find repos where the user had activity in the date range."""
    events = gh_api(f"users/{GH_USERNAME}/events", {"per_page": "100"})
    repos = set()
    for event in events:
        created = parse_date(event.get("created_at"))
        if not created:
            continue
        # Events API returns newest first; stop once we're before the range
        if created < start:
            break
        if not date_in_range(created, start, end):
            continue
        repo_name = event.get("repo", {}).get("name", "")
        if repo_name.startswith(f"{ORG}/"):
            repos.add(repo_name)
    return sorted(repos)


# ---------------------------------------------------------------------------
# Per-repo activity gathering
# ---------------------------------------------------------------------------

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
    commits = gh_api(f"repos/{repo}/commits", {
        "author": GIT_AUTHOR,
        "since": f"{api_since}T00:00:00Z",
        "until": f"{api_until}T00:00:00Z",
        "per_page": "100"
    })
    for c in commits:
        day = parse_date(c.get("commit", {}).get("author", {}).get("date", ""))
        if not date_in_range(day, start, end):
            continue
        msg = c.get("commit", {}).get("message", "").split("\n")[0]
        for ticket_num in extract_ticket_refs(msg):
            activity[day][key(ticket_num)]["sources"].add("commits")

    # --- 2. PRs authored ---
    # Search with wider window (api dates) since GitHub search uses UTC
    prs = gh_search(repo, "pr", [f"--search=created:>={api_since} created:<={api_until}"])
    for pr in prs:
        day = parse_date(pr.get("createdAt"))
        if not date_in_range(day, start, end):
            continue
        num = pr["number"]
        title = strip_conventional_prefix(pr.get("title", ""))
        pr_numbers.add(num)
        activity[day][key(num)]["title"] = title
        activity[day][key(num)]["sources"].add("authored-pr")
        merge_day = parse_date(pr.get("mergedAt"))
        if merge_day and date_in_range(merge_day, start, end) and merge_day != day:
            activity[merge_day][key(num)]["title"] = title
            activity[merge_day][key(num)]["sources"].add("authored-pr")
        for ref in extract_ticket_refs(pr.get("body", "")):
            activity[day][key(ref)]["sources"].add("pr-ref")

    # --- 3. Issue comments ---
    issue_comments = gh_api(f"repos/{repo}/issues/comments", {
        "since": f"{api_since}T00:00:00Z",
        "per_page": "100"
    })
    issue_comment_numbers = set()
    for ic in issue_comments:
        if ic.get("user", {}).get("login") != GH_USERNAME:
            continue
        day = parse_date(ic.get("created_at"))
        if not date_in_range(day, start, end):
            continue
        issue_num = int(ic.get("issue_url", "").split("/")[-1])
        issue_comment_numbers.add(issue_num)
        activity[day][key(issue_num)]["sources"].add("issue-comment")

    # --- 4. PR review comments (inline) ---
    pr_review_comments = gh_api(f"repos/{repo}/pulls/comments", {
        "since": f"{api_since}T00:00:00Z",
        "per_page": "100"
    })
    pr_comment_numbers = set()
    for rc in pr_review_comments:
        if rc.get("user", {}).get("login") != GH_USERNAME:
            continue
        day = parse_date(rc.get("created_at"))
        if not date_in_range(day, start, end):
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
        reviews = gh_api(f"repos/{repo}/pulls/{pr_num}/reviews", paginate=False)
        for rev in (reviews if isinstance(reviews, list) else []):
            if rev.get("user", {}).get("login") != GH_USERNAME:
                continue
            day = parse_date(rev.get("submitted_at"))
            if date_in_range(day, start, end):
                review_pr_numbers.add(pr_num)
                title = strip_conventional_prefix(pr.get("title", ""))
                activity[day][key(pr_num)]["title"] = title
                activity[day][key(pr_num)]["sources"].add("pr-review")

    # --- 6. Issues authored ---
    issues = gh_search(repo, "issue", [f"--search=created:>={api_since} created:<={api_until}"])
    for issue in issues:
        day = parse_date(issue.get("createdAt"))
        if not date_in_range(day, start, end):
            continue
        num = issue["number"]
        title = strip_conventional_prefix(issue.get("title", ""))
        activity[day][key(num)]["title"] = title
        activity[day][key(num)]["sources"].add("authored-issue")

    # --- Fetch missing titles ---
    known_titles = {}
    for day_data in activity.values():
        for k, info in day_data.items():
            if info["title"] and k not in known_titles:
                known_titles[k] = info["title"]

    for day_data in activity.values():
        for k, info in day_data.items():
            if not info["title"] and k in known_titles:
                info["title"] = known_titles[k]

    all_keys = set()
    for day_data in activity.values():
        all_keys.update(day_data.keys())

    for k in all_keys:
        if k not in known_titles:
            title = fetch_item_title(k[0], k[1])
            title = strip_conventional_prefix(title)
            for day_data in activity.values():
                if k in day_data and not day_data[k]["title"]:
                    day_data[k]["title"] = title

    return activity, pr_numbers, pr_comment_numbers, review_pr_numbers, prs


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Gather GitHub activity")
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    start = args.start_date
    end = args.end_date

    # Widen the API query window by 1 day on each side to account for
    # UTC vs local timezone offset (e.g., 10pm CDT = next day in UTC)
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    api_since = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    api_until = (end_dt + timedelta(days=2)).strftime("%Y-%m-%d")

    # Discover repos — use wider window so timezone edge cases are caught
    repos = discover_repos(api_since, api_until)
    if not repos:
        print(f"No activity found for {GH_USERNAME} between {start} and {end}.")
        return

    print(f"Repos with activity: {', '.join(r.split('/')[-1] for r in repos)}", file=sys.stderr)

    # Gather activity from all repos
    # merged: day -> {(repo, number): {"title", "sources"}}
    merged_activity = defaultdict(lambda: defaultdict(lambda: {"title": "", "sources": set()}))
    all_pr_numbers = set()       # (repo, num)
    all_pr_comment_numbers = set()
    all_review_pr_numbers = set()
    all_prs = []                 # list of (repo, pr_dict)

    for repo in repos:
        print(f"Gathering activity from {repo}...", file=sys.stderr)
        activity, pr_nums, pr_comment_nums, review_pr_nums, prs = \
            gather_repo_activity(repo, start, end, api_since, api_until)

        for day, day_data in activity.items():
            for k, info in day_data.items():
                entry = merged_activity[day][k]
                if info["title"]:
                    entry["title"] = info["title"]
                entry["sources"].update(info["sources"])

        all_pr_numbers.update((repo, n) for n in pr_nums)
        all_pr_comment_numbers.update((repo, n) for n in pr_comment_nums)
        all_review_pr_numbers.update((repo, n) for n in review_pr_nums)
        all_prs.extend((repo, pr) for pr in prs)

    # Determine display format
    multi_repo = len(repos) > 1

    def format_ticket(repo, num, title):
        short_repo = repo.split("/")[-1]
        if multi_repo:
            return f"{short_repo}#{num}: {title}"
        return f"#{num}: {title}"

    # Build output
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")

    print(f"## Weekly Activity: {start_dt.strftime('%A')} {start} - {end_dt.strftime('%A')} {end}, {start_dt.year}")
    print()
    print("| Day       | Tickets & PRs | Source |")
    print("|-----------|---------------|--------|")

    all_tickets = set()
    current = start_dt
    while current <= end_dt:
        day_str = current.strftime("%Y-%m-%d")
        day_abbr = DAY_NAMES[current.weekday()]
        day_label = f"{day_abbr} {current.strftime('%m/%d')}"

        if day_str in merged_activity and merged_activity[day_str]:
            tickets = sorted(merged_activity[day_str].items(), key=lambda x: (x[0][0], x[0][1]))
            ticket_parts = []
            source_parts = []
            for (repo, num), info in tickets:
                title = info["title"] or f"(unknown #{num})"
                ticket_parts.append(format_ticket(repo, num, title))
                primary = sorted(info["sources"])[0]
                source_parts.append(primary)
                all_tickets.add((repo, num))

            print(f"| {day_label} | {', '.join(ticket_parts)} | {', '.join(source_parts)} |")
        else:
            print(f"| {day_label} | No activity | |")

        current += timedelta(days=1)

    # Summary
    all_pr_keys = (all_pr_numbers | all_pr_comment_numbers | all_review_pr_numbers) & all_tickets
    merged_count = sum(1 for repo, pr in all_prs if (repo, pr["number"]) in all_pr_keys and pr.get("mergedAt"))
    open_count = len(all_pr_keys) - merged_count

    print()
    print("### Summary")
    print(f"- Repos: {', '.join(r.split('/')[-1] for r in repos)}")
    print(f"- Total Tickets Touched: {len(all_tickets)}")
    print(f"- Total PRs: {len(all_pr_keys)} ({merged_count} merged, {open_count} open)")


if __name__ == "__main__":
    main()
