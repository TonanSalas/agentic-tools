#!/usr/bin/env python3
"""
Gather Linear comment volume (per ticket, per day) across the whole workspace
for a date range, authenticated via a personal API key (LINEAR_API_KEY).
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOCAL_TZ = timezone(timedelta(hours=-5))  # CDT (US Central Daylight)
LINEAR_API_URL = "https://api.linear.app/graphql"

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_TTL_SECONDS = 3600

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

COMMENTS_QUERY = """
query($after: String, $gte: DateTimeOrDuration!, $lte: DateTimeOrDuration!) {
  comments(
    first: 100
    after: $after
    filter: { createdAt: { gte: $gte, lte: $lte } }
    orderBy: createdAt
  ) {
    nodes {
      id
      createdAt
      issue { identifier }
      user { name }
    }
    pageInfo { hasNextPage endCursor }
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


def run_query(query, variables, api_key):
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_API_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"Warning: Linear API request failed: {e}", file=sys.stderr)
        return None


MAX_PAGES = 200  # generous cap (~20k comments at 100/page) to guard against a misbehaving API looping forever


def fetch_comments(api_since, api_until, api_key):
    comments = []
    after = None
    gte = f"{api_since}T00:00:00.000Z"
    lte = f"{api_until}T23:59:59.999Z"
    for _ in range(MAX_PAGES):
        result = run_query(COMMENTS_QUERY, {"after": after, "gte": gte, "lte": lte}, api_key)
        if not result:
            break
        if "errors" in result:
            print(f"Warning: Linear API returned errors: {result['errors']}", file=sys.stderr)
            break
        data = (result.get("data") or {}).get("comments") or {}
        comments.extend(data.get("nodes") or [])
        page_info = data.get("pageInfo") or {}
        if page_info.get("hasNextPage"):
            after = page_info.get("endCursor")
        else:
            break
    else:
        print(f"Warning: hit MAX_PAGES ({MAX_PAGES}) pagination cap; results may be incomplete", file=sys.stderr)
    return comments


def gather_all(start, end, api_key):
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    api_since = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    api_until = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    comments = fetch_comments(api_since, api_until, api_key)

    days = {}
    tickets = {}
    ticket_authors = {}
    for c in comments:
        day = parse_date(c.get("createdAt"))
        if not day or not (start <= day <= end):
            continue
        days[day] = days.get(day, 0) + 1
        ticket = (c.get("issue") or {}).get("identifier", "unknown")
        tickets[ticket] = tickets.get(ticket, 0) + 1
        author = (c.get("user") or {}).get("name") or "Unknown"
        by_author = ticket_authors.setdefault(ticket, {})
        by_author[author] = by_author.get(author, 0) + 1

    return {
        "generated_at": datetime.now(LOCAL_TZ).isoformat(),
        "start": start,
        "end": end,
        "days": days,
        "tickets": tickets,
        "ticket_authors": ticket_authors,
    }


def render_markdown(data):
    start, end = data["start"], data["end"]
    days = data["days"]
    tickets = data["tickets"]
    ticket_authors = data.get("ticket_authors", {})

    if not days:
        return f"No Linear comments found between {start} and {end}."

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")

    lines = []
    lines.append("### Linear Comments by Ticket and Author")
    lines.append("")
    lines.append("| Ticket  | Author | Comments |")
    lines.append("|---------|--------|----------|")
    for ticket in sorted(ticket_authors.keys()):
        by_author = ticket_authors[ticket]
        for author, count in sorted(by_author.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| {ticket} | {author} | {count} |")

    lines.append("")
    lines.append("### Linear Comments by Day")
    lines.append("")
    lines.append("| Day       | Comments |")
    lines.append("|-----------|----------|")
    current = start_dt
    while current <= end_dt:
        day_str = current.strftime("%Y-%m-%d")
        day_abbr = DAY_NAMES[current.weekday()]
        lines.append(f"| {day_abbr} {current.strftime('%m/%d')} | {days.get(day_str, 0)} |")
        current += timedelta(days=1)

    lines.append("")
    lines.append("### Linear Comments by Ticket")
    lines.append("")
    lines.append("| Ticket  | Comments |")
    lines.append("|---------|----------|")
    for ticket, count in sorted(tickets.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {ticket} | {count} |")

    total = sum(days.values())
    lines.append("")
    lines.append(f"**Total comments:** {total}")
    return "\n".join(lines)


def cache_path_for(cache_dir, start, end):
    return Path(cache_dir) / f"linear_{start}_{end}.json"


def cache_is_fresh(path, end_date):
    if not path.exists():
        return False
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    if end_date < today:
        return True
    return (time.time() - path.stat().st_mtime) < CACHE_TTL_SECONDS


def main():
    parser = argparse.ArgumentParser(description="Gather Linear comment volume across the workspace")
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of markdown")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        print("Error: LINEAR_API_KEY not set", file=sys.stderr)
        sys.exit(2)

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
        data = gather_all(start, end, api_key)
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
