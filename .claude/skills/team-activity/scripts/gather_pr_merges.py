#!/usr/bin/env python3
"""
Gather org-wide merged-PR counts across all dragonflyic repos for a date range.

Uses a single paginated GitHub GraphQL search (not gh search prs --json, which
does not expose mergedAt) to get exact merge timestamps for every PR merged in
the org during the range, then buckets by local-tz day and by repo.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ORG = "dragonflyic"
LOCAL_TZ = timezone(timedelta(hours=-5))  # CDT (US Central Daylight)

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_TTL_SECONDS = 3600

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

PR_SEARCH_QUERY = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number
        title
        mergedAt
        repository { name }
      }
    }
  }
}
"""


def parse_date(iso_str):
    """Convert a UTC ISO timestamp to a local-timezone YYYY-MM-DD date."""
    if not iso_str:
        return None
    try:
        cleaned = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned).astimezone(LOCAL_TZ)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso_str[:10]


def fetch_merged_prs(api_since, api_until):
    """Paginate through GitHub's GraphQL search for merged PRs across the whole org."""
    prs = []
    after = None
    query_str = f"org:{ORG} is:pr is:merged merged:{api_since}..{api_until}"
    while True:
        cmd = ["gh", "api", "graphql", "-f", f"query={PR_SEARCH_QUERY}", "-f", f"q={query_str}"]
        if after:
            cmd += ["-f", f"after={after}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Warning: gh api graphql failed: {result.stderr}", file=sys.stderr)
            break
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            print("Warning: failed to parse gh api graphql output", file=sys.stderr)
            break
        search = (data.get("data") or {}).get("search") or {}
        for node in search.get("nodes") or []:
            if node and node.get("mergedAt"):
                prs.append(node)
        page_info = search.get("pageInfo") or {}
        if page_info.get("hasNextPage"):
            after = page_info.get("endCursor")
        else:
            break
    return prs


def gather_all(start, end):
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    api_since = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    api_until = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    prs = fetch_merged_prs(api_since, api_until)

    days = {}
    for pr in prs:
        day = parse_date(pr.get("mergedAt"))
        if not day or not (start <= day <= end):
            continue
        repo = (pr.get("repository") or {}).get("name", "unknown")
        entry = days.setdefault(day, {"total": 0, "by_repo": {}})
        entry["total"] += 1
        entry["by_repo"][repo] = entry["by_repo"].get(repo, 0) + 1

    return {
        "generated_at": datetime.now(LOCAL_TZ).isoformat(),
        "start": start,
        "end": end,
        "days": days,
    }


def render_markdown(data):
    start, end = data["start"], data["end"]
    days = data["days"]

    if not days:
        return f"No merged PRs found across {ORG} between {start} and {end}."

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")

    lines = []
    lines.append(f"### PRs Merged: {start} - {end}")
    lines.append("")
    lines.append("| Day       | Total | By Repo |")
    lines.append("|-----------|-------|---------|")

    current = start_dt
    while current <= end_dt:
        day_str = current.strftime("%Y-%m-%d")
        day_abbr = DAY_NAMES[current.weekday()]
        entry = days.get(day_str, {"total": 0, "by_repo": {}})
        by_repo = ", ".join(f"{repo}: {count}" for repo, count in sorted(entry["by_repo"].items()))
        lines.append(f"| {day_abbr} {current.strftime('%m/%d')} | {entry['total']} | {by_repo or '-'} |")
        current += timedelta(days=1)

    total = sum(e["total"] for e in days.values())
    lines.append("")
    lines.append(f"**Total merged PRs:** {total}")
    return "\n".join(lines)


def cache_path_for(cache_dir, start, end):
    return Path(cache_dir) / f"prs_{start}_{end}.json"


def cache_is_fresh(path, end_date):
    if not path.exists():
        return False
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    if end_date < today:
        return True
    return (time.time() - path.stat().st_mtime) < CACHE_TTL_SECONDS


def main():
    parser = argparse.ArgumentParser(description="Gather org-wide merged PR counts")
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of markdown")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    start, end = args.start_date, args.end_date
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
