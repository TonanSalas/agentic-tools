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
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ORG = "dragonflyic"
GH_USERNAME = "tonansalas-dragonfly"
GIT_AUTHOR = "tonansalas"
LOCAL_TZ = timezone(timedelta(hours=-5))  # CDT (US Central Daylight)

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_TTL_SECONDS = 3600  # 1h for current/future weeks; closed weeks cached forever

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


def fetch_item_meta(repo, number):
    """Fetch issue/PR metadata (title, state, state_reason, is_pr, merged) in one call.

    The /issues/{n} endpoint covers both issues and PRs; for PRs it includes a
    `pull_request` field with `merged_at`. Returns a dict with safe defaults
    if the call fails (e.g. ticket from another repo).
    """
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{number}"],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {
            "title": f"(unknown #{number})",
            "state": "unknown",
            "state_reason": None,
            "is_pr": False,
            "merged": None,
        }
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "title": f"(unknown #{number})",
            "state": "unknown",
            "state_reason": None,
            "is_pr": False,
            "merged": None,
        }
    pr_info = data.get("pull_request") or {}
    is_pr = bool(pr_info)
    merged = bool(pr_info.get("merged_at")) if is_pr else None
    return {
        "title": data.get("title", f"(unknown #{number})"),
        "state": (data.get("state") or "unknown").lower(),
        "state_reason": data.get("state_reason"),
        "is_pr": is_pr,
        "merged": merged,
    }


def fetch_item_title(repo, number):
    """Backwards-compatible: return just the title string."""
    return fetch_item_meta(repo, number)["title"]


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

    # --- Collect all referenced (repo, number) keys ---
    all_keys = set()
    for day_data in activity.values():
        all_keys.update(day_data.keys())

    # --- Fetch metadata (title + state) for every ticket via one API call each ---
    meta_by_key = {}
    for k in all_keys:
        meta = fetch_item_meta(k[0], k[1])
        meta["title"] = strip_conventional_prefix(meta["title"])
        meta_by_key[k] = meta

    # --- Backfill titles into per-day activity ---
    for day_data in activity.values():
        for k, info in day_data.items():
            if not info["title"] and k in meta_by_key:
                info["title"] = meta_by_key[k]["title"]

    return activity, pr_numbers, pr_comment_numbers, review_pr_numbers, prs, meta_by_key


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def cache_path_for(cache_dir, start, end):
    return Path(cache_dir) / f"{start}_{end}.json"


def cache_is_fresh(path, end_date):
    """Closed weeks (end < today) cache forever; current/future weeks expire after CACHE_TTL_SECONDS."""
    if not path.exists():
        return False
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    if end_date < today:
        return True
    return (time.time() - path.stat().st_mtime) < CACHE_TTL_SECONDS


# ---------------------------------------------------------------------------
# Data assembly & rendering
# ---------------------------------------------------------------------------

def gather_all(start, end):
    """Run the full discovery + per-repo gather and return a JSON-serializable dict."""
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    api_since = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    api_until = (end_dt + timedelta(days=2)).strftime("%Y-%m-%d")

    repos = discover_repos(api_since, api_until)
    if not repos:
        return {
            "generated_at": datetime.now(LOCAL_TZ).isoformat(),
            "start": start,
            "end": end,
            "repos": [],
            "days": {},
            "tickets": [],
        }

    print(f"Repos with activity: {', '.join(r.split('/')[-1] for r in repos)}", file=sys.stderr)

    merged_activity = defaultdict(lambda: defaultdict(lambda: {"title": "", "sources": set()}))
    merged_meta = {}  # (repo, num) -> meta dict

    for repo in repos:
        print(f"Gathering activity from {repo}...", file=sys.stderr)
        activity, _pr_nums, _pr_comment_nums, _review_pr_nums, _prs, meta_by_key = \
            gather_repo_activity(repo, start, end, api_since, api_until)

        for day, day_data in activity.items():
            for k, info in day_data.items():
                entry = merged_activity[day][k]
                if info["title"]:
                    entry["title"] = info["title"]
                entry["sources"].update(info["sources"])

        merged_meta.update(meta_by_key)

    # Build per-ticket dedup view: (repo, num) -> {meta, days, sources}
    tickets_index = {}
    for day, day_data in merged_activity.items():
        for (repo, num), info in day_data.items():
            t = tickets_index.setdefault((repo, num), {
                "days": set(),
                "sources": set(),
            })
            t["days"].add(day)
            t["sources"].update(info["sources"])

    tickets_list = []
    for (repo, num), t in sorted(tickets_index.items()):
        meta = merged_meta.get((repo, num), {})
        tickets_list.append({
            "repo": repo.split("/")[-1],
            "number": num,
            "title": meta.get("title") or f"(unknown #{num})",
            "state": meta.get("state", "unknown"),
            "state_reason": meta.get("state_reason"),
            "is_pr": meta.get("is_pr", False),
            "merged": meta.get("merged"),
            "days": sorted(t["days"]),
            "sources": sorted(t["sources"]),
        })

    # Per-day view (for workday-timelogger): day -> [ticket dicts]
    days_view = {}
    ticket_lookup = {(t["repo"], t["number"]): t for t in tickets_list}
    for day, day_data in merged_activity.items():
        items = []
        for (repo, num), info in sorted(day_data.items()):
            short = repo.split("/")[-1]
            base = ticket_lookup.get((short, num), {})
            items.append({
                "repo": short,
                "number": num,
                "title": info["title"] or base.get("title") or f"(unknown #{num})",
                "state": base.get("state", "unknown"),
                "state_reason": base.get("state_reason"),
                "is_pr": base.get("is_pr", False),
                "merged": base.get("merged"),
                "sources": sorted(info["sources"]),
            })
        days_view[day] = items

    return {
        "generated_at": datetime.now(LOCAL_TZ).isoformat(),
        "start": start,
        "end": end,
        "repos": [r.split("/")[-1] for r in repos],
        "days": days_view,
        "tickets": tickets_list,
    }


def render_markdown(data):
    """Render the dict from gather_all() as the original markdown table."""
    start = data["start"]
    end = data["end"]
    repos = data["repos"]

    if not repos:
        return f"No activity found for {GH_USERNAME} between {start} and {end}."

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    multi_repo = len(repos) > 1

    def format_ticket(repo, num, title):
        if multi_repo:
            return f"{repo}#{num}: {title}"
        return f"#{num}: {title}"

    lines = []
    lines.append(f"## Weekly Activity: {start_dt.strftime('%A')} {start} - {end_dt.strftime('%A')} {end}, {start_dt.year}")
    lines.append("")
    lines.append("| Day       | Tickets & PRs | Source |")
    lines.append("|-----------|---------------|--------|")

    current = start_dt
    while current <= end_dt:
        day_str = current.strftime("%Y-%m-%d")
        day_abbr = DAY_NAMES[current.weekday()]
        day_label = f"{day_abbr} {current.strftime('%m/%d')}"

        items = data["days"].get(day_str, [])
        if items:
            ticket_parts = [format_ticket(it["repo"], it["number"], it["title"]) for it in items]
            source_parts = [it["sources"][0] if it["sources"] else "" for it in items]
            lines.append(f"| {day_label} | {', '.join(ticket_parts)} | {', '.join(source_parts)} |")
        else:
            lines.append(f"| {day_label} | No activity | |")
        current += timedelta(days=1)

    # Summary
    pr_tickets = [t for t in data["tickets"] if t["is_pr"]]
    merged_count = sum(1 for t in pr_tickets if t["merged"])
    open_count = len(pr_tickets) - merged_count

    lines.append("")
    lines.append("### Summary")
    lines.append(f"- Repos: {', '.join(repos)}")
    lines.append(f"- Total Tickets Touched: {len(data['tickets'])}")
    lines.append(f"- Total PRs: {len(pr_tickets)} ({merged_count} merged, {open_count} open)")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Gather GitHub activity")
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--json", action="store_true",
                        help="Emit structured JSON (with ticket state) instead of markdown")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR),
                        help="Cache directory (default: <skill>/cache/)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Force a fresh fetch and overwrite any cached result")
    args = parser.parse_args()

    start = args.start_date
    end = args.end_date
    cache_dir = Path(args.cache_dir)
    cache_path = cache_path_for(cache_dir, start, end)

    data = None
    if not args.no_cache and cache_is_fresh(cache_path, end):
        try:
            data = json.loads(cache_path.read_text())
            print(f"Using cache: {cache_path}", file=sys.stderr)
        except (json.JSONDecodeError, OSError):
            data = None

    if data is None:
        data = gather_all(start, end)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, indent=2))
        except OSError as e:
            print(f"Warning: failed to write cache: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(render_markdown(data))


if __name__ == "__main__":
    main()
