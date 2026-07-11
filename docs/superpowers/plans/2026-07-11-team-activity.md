# Team Activity Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/team-activity` skill that reports org-wide merged-PR counts (per day, per
repo) across all `dragonflyic` GitHub repos, and Linear comment volume (per ticket, per day)
across the whole Linear workspace, for a given date range.

**Architecture:** One new skill directory, `.claude/skills/team-activity/`, containing two
independent, cacheable Python scripts (`gather_pr_merges.py` for GitHub, `gather_linear_comments.py`
for Linear) and a `SKILL.md` that runs both and renders one combined markdown report. No shared
code between the two scripts — each is a self-contained CLI tool following the conventions of
`weekly-activity/scripts/gather_activity.py`.

**Tech Stack:** Python 3 standard library only (`argparse`, `json`, `subprocess`, `urllib.request`,
`datetime`). `gh` CLI (already authenticated) for GitHub. Linear's GraphQL API via a personal API
key (`LINEAR_API_KEY`, already added to `.env`) for Linear.

## Global Constraints

- No automated test framework exists in this repo (skills-only, no CI, no build system, per
  `CLAUDE.md`) — verification throughout this plan is manual: run the script, inspect the JSON/
  markdown output, spot-check counts against the GitHub/Linear web UI.
- Local timezone for all day-bucketing is `UTC-5` (`timezone(timedelta(hours=-5))`), matching
  `gather_activity.py`'s `LOCAL_TZ` — copy this constant exactly, don't invent a new one.
- `LINEAR_API_KEY` must never be printed, logged, or included in any committed file. It lives in
  `.env`, which is already gitignored.
- Both scripts must degrade gracefully on API failure (print a warning to stderr, return partial/
  empty data) rather than raising an unhandled exception — matches `gather_activity.py`'s
  `gh_api`/`gh_search` error handling.
- Cache directory: `.claude/skills/team-activity/cache/` — must be added to `.gitignore` (mirrors
  the existing `.claude/skills/weekly-activity/cache/` entry).
- Both scripts group PR-merges/comments by **local-tz date**, not UTC date. Since GitHub's and
  Linear's date filters are UTC-based, both scripts must widen their API query window by ±1 day
  and then filter results down to the exact local-date range afterward — this is required for
  correctness near day boundaries, not an optional nicety.

---

### Task 1: `gather_pr_merges.py` — org-wide merged PR counts

**Files:**
- Create: `.claude/skills/team-activity/scripts/gather_pr_merges.py`
- Modify: `.gitignore` (add `.claude/skills/team-activity/cache/`)

**Interfaces:**
- Produces (consumed by Task 3's `SKILL.md`): a CLI invoked as
  `python3 gather_pr_merges.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--json] [--no-cache] [--cache-dir PATH]`.
  With `--json`, prints a JSON object to stdout:
  ```json
  {
    "generated_at": "<iso8601>",
    "start": "YYYY-MM-DD",
    "end": "YYYY-MM-DD",
    "days": {
      "YYYY-MM-DD": {"total": 3, "by_repo": {"repo-a": 2, "repo-b": 1}}
    }
  }
  ```
  Without `--json`, prints a rendered markdown table to stdout (see Step 6).

- [ ] **Step 1: Scaffold the skill directory and write the GraphQL fetch function**

Create `.claude/skills/team-activity/scripts/gather_pr_merges.py`:

```python
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


if __name__ == "__main__":
    print(json.dumps(fetch_merged_prs("2026-07-09", "2026-07-11"), indent=2)[:2000])
```

The `if __name__ == "__main__"` block at the bottom is a temporary manual-check hook — it gets
replaced by the real `main()` in Step 5.

- [ ] **Step 2: Manually verify the fetch function against real data**

Run:
```bash
python3 .claude/skills/team-activity/scripts/gather_pr_merges.py
```

Expected: a JSON array (truncated to 2000 chars) of PR objects, each with `number`, `title`,
`mergedAt` (a full ISO timestamp like `"2026-07-10T23:04:42Z"`), and `repository.name`. Confirm
`mergedAt` is present and looks like a real timestamp, not `null` — this is the field
`gh search prs --json` does NOT provide, which is why this task uses `gh api graphql` instead.

- [ ] **Step 3: Add local-tz bucketing (`gather_all`)**

Replace the temporary `if __name__ == "__main__"` block with:

```python
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
```

- [ ] **Step 4: Manually verify `gather_all` produces correctly bucketed counts**

Add a temporary check at the bottom of the file:

```python
if __name__ == "__main__":
    print(json.dumps(gather_all("2026-07-10", "2026-07-10"), indent=2))
```

Run:
```bash
python3 .claude/skills/team-activity/scripts/gather_pr_merges.py
```

Expected: a `days` object with key `"2026-07-10"` whose `total` is a positive integer and whose
`by_repo` breaks that total down by repo name (e.g. `agentic-org`, `insurance_portal`,
`agentic-org-runner`) — the totals in `by_repo` must sum to `total`. Spot-check the total against
GitHub's search UI for `org:dragonflyic is:pr is:merged merged:2026-07-10` (or
`gh api graphql` run manually with the same query) — exact equality isn't required (UTC/local-day
edge effects), but the count should be in the same ballpark and never zero when PRs are known to
exist that day.

- [ ] **Step 5: Add markdown rendering, caching, and the real CLI**

Replace the temporary `if __name__ == "__main__"` block with:

```python
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
```

- [ ] **Step 6: Manually verify the full CLI, including caching**

Run:
```bash
python3 .claude/skills/team-activity/scripts/gather_pr_merges.py --start-date 2026-07-10 --end-date 2026-07-11
```

Expected: a markdown table with two rows (`Fri 07/10`, `Sat 07/11`), a `By Repo` column listing
repo names and counts, and a `**Total merged PRs:**` line at the bottom.

Then confirm caching works:
```bash
ls .claude/skills/team-activity/cache/
python3 .claude/skills/team-activity/scripts/gather_pr_merges.py --start-date 2026-07-10 --end-date 2026-07-11
```

Expected: `prs_2026-07-10_2026-07-11.json` exists after the first run; the second run prints
`Using cache: ...` to stderr instead of re-querying GitHub.

- [ ] **Step 7: Add the cache directory to `.gitignore`**

Edit `.gitignore`, adding a new line after the existing `.claude/skills/weekly-activity/cache/`
entry:

```
.claude/skills/team-activity/cache/
```

- [ ] **Step 8: Commit**

```bash
git add .claude/skills/team-activity/scripts/gather_pr_merges.py .gitignore
git commit -m "$(cat <<'EOF'
Add gather_pr_merges.py for org-wide merged PR counts

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `gather_linear_comments.py` — org-wide Linear comment volume

**Files:**
- Create: `.claude/skills/team-activity/scripts/gather_linear_comments.py`

**Interfaces:**
- Produces (consumed by Task 3's `SKILL.md`): a CLI invoked as
  `python3 gather_linear_comments.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--json] [--no-cache] [--cache-dir PATH]`.
  Reads `LINEAR_API_KEY` from the environment (the caller is responsible for having it exported,
  e.g. via `set -a; source .env; set +a` — this script does not read `.env` itself).
  - Exits with code `2` and a stderr message if `LINEAR_API_KEY` is unset — no stdout output in
    that case, so `SKILL.md` (Task 3) can detect this exit code and skip the Linear section.
  - With `--json`, prints:
    ```json
    {
      "generated_at": "<iso8601>",
      "start": "YYYY-MM-DD",
      "end": "YYYY-MM-DD",
      "days": {"YYYY-MM-DD": 12},
      "tickets": {"DRA-221": 5, "DRA-196": 3}
    }
    ```
  - Without `--json`, prints a rendered markdown (two tables — see Step 6).

- [ ] **Step 1: Write the GraphQL fetch function**

Create `.claude/skills/team-activity/scripts/gather_linear_comments.py`:

```python
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


def fetch_comments(api_since, api_until, api_key):
    comments = []
    after = None
    gte = f"{api_since}T00:00:00.000Z"
    lte = f"{api_until}T23:59:59.999Z"
    while True:
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
    return comments


if __name__ == "__main__":
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        print("Error: LINEAR_API_KEY not set", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(fetch_comments("2026-07-09", "2026-07-11", api_key), indent=2)[:2000])
```

The `if __name__ == "__main__"` block is a temporary manual-check hook, replaced in Step 5.

- [ ] **Step 2: Manually verify the fetch function against real data**

Run:
```bash
set -a; source .env; set +a
python3 .claude/skills/team-activity/scripts/gather_linear_comments.py
```

Expected: a JSON array (truncated to 2000 chars) of comment objects, each with `id`, `createdAt`
(a full ISO timestamp), and `issue.identifier` (e.g. `"DRA-221"`). If `LINEAR_API_KEY` isn't
exported, confirm you instead see `Error: LINEAR_API_KEY not set` on stderr and exit code `2`
(`echo $?` after running).

- [ ] **Step 3: Add local-tz bucketing (`gather_all`)**

Replace the temporary `if __name__ == "__main__"` block with:

```python
def gather_all(start, end, api_key):
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    api_since = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    api_until = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    comments = fetch_comments(api_since, api_until, api_key)

    days = {}
    tickets = {}
    for c in comments:
        day = parse_date(c.get("createdAt"))
        if not day or not (start <= day <= end):
            continue
        days[day] = days.get(day, 0) + 1
        ticket = (c.get("issue") or {}).get("identifier", "unknown")
        tickets[ticket] = tickets.get(ticket, 0) + 1

    return {
        "generated_at": datetime.now(LOCAL_TZ).isoformat(),
        "start": start,
        "end": end,
        "days": days,
        "tickets": tickets,
    }
```

- [ ] **Step 4: Manually verify `gather_all` produces correctly bucketed counts**

Add a temporary check at the bottom of the file:

```python
if __name__ == "__main__":
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        print("Error: LINEAR_API_KEY not set", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(gather_all("2026-07-10", "2026-07-10", api_key), indent=2))
```

Run:
```bash
set -a; source .env; set +a
python3 .claude/skills/team-activity/scripts/gather_linear_comments.py
```

Expected: `days` has key `"2026-07-10"` with a positive integer count; `tickets` maps ticket
identifiers (e.g. `"DRA-221"`) to positive counts, and the sum of all `tickets` values equals the
`days["2026-07-10"]` value (every comment counted in exactly one ticket and one day). Spot-check
one ticket's count by opening it in the Linear UI and counting comments dated 2026-07-10.

- [ ] **Step 5: Add markdown rendering, caching, and the real CLI**

Replace the temporary `if __name__ == "__main__"` block with:

```python
def render_markdown(data):
    start, end = data["start"], data["end"]
    days = data["days"]
    tickets = data["tickets"]

    if not days:
        return f"No Linear comments found between {start} and {end}."

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")

    lines = []
    lines.append(f"### Linear Comments by Day: {start} - {end}")
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
    for ticket, count in sorted(tickets.items(), key=lambda kv: -kv[1]):
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
```

- [ ] **Step 6: Manually verify the full CLI, including caching and the missing-key path**

Run:
```bash
set -a; source .env; set +a
python3 .claude/skills/team-activity/scripts/gather_linear_comments.py --start-date 2026-07-10 --end-date 2026-07-11
```

Expected: a "Linear Comments by Day" table with two rows, a "Linear Comments by Ticket" table
sorted descending by count, and a `**Total comments:**` line.

Then confirm caching:
```bash
ls .claude/skills/team-activity/cache/
python3 .claude/skills/team-activity/scripts/gather_linear_comments.py --start-date 2026-07-10 --end-date 2026-07-11
```

Expected: `linear_2026-07-10_2026-07-11.json` exists; the second run prints `Using cache: ...` to
stderr.

Then confirm graceful failure when the key is missing:
```bash
unset LINEAR_API_KEY
python3 .claude/skills/team-activity/scripts/gather_linear_comments.py --start-date 2026-07-10 --end-date 2026-07-11
echo "exit code: $?"
```

Expected: `Error: LINEAR_API_KEY not set` on stderr, no stdout, `exit code: 2`.

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/team-activity/scripts/gather_linear_comments.py
git commit -m "$(cat <<'EOF'
Add gather_linear_comments.py for org-wide Linear comment volume

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `SKILL.md` — orchestration and combined report

**Files:**
- Create: `.claude/skills/team-activity/SKILL.md`

**Interfaces:**
- Consumes: `gather_pr_merges.py` and `gather_linear_comments.py` CLIs from Tasks 1 and 2 (exact
  flags and exit-code-2-on-missing-key behavior as documented above).
- Produces: the `/team-activity` slash command, invocable by the user with an optional
  `date-range` argument.

- [ ] **Step 1: Write `SKILL.md`**

Create `.claude/skills/team-activity/SKILL.md`:

```markdown
---
name: team-activity
description: Report org-wide merged PR counts (per day, per repo) across all dragonflyic repos, and Linear comment volume (per ticket, per day) across the whole workspace, for a date range. Use for team activity, team velocity, or communication-volume reports — not for personal activity (use weekly-activity for that).
user-invocable: true
allowed-tools: Bash
arguments:
  - name: date-range
    description: "Optional date range in YYYY-MM-DD..YYYY-MM-DD format (e.g. 2026-07-06..2026-07-11). Defaults to current week (Monday through today)."
    required: false
---

# Team Activity Report

Report two things for a date range, across the whole `dragonflyic` org / Linear workspace (not
scoped to one person):

1. Merged PRs per day, with a per-repo breakdown (`scripts/gather_pr_merges.py`).
2. Linear comment volume per ticket and per day (`scripts/gather_linear_comments.py`).

## Step 1: Compute dates

If the user provided a `date-range` argument, parse start and end dates from it. Otherwise
default to the current week (Monday through today):

\`\`\`bash
# If date-range provided:
START_DATE="<start>"
END_DATE="<end>"

# If no date-range:
START_DATE=$(date -v-Mon +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)
\`\`\`

If the range spans more than 90 days, tell the user this may be slow (org-wide PR search and
per-comment Linear pagination both scale with range size) and confirm before proceeding.

## Step 2: Run the GitHub PR-merges script

\`\`\`bash
python3 "<skill-directory>/scripts/gather_pr_merges.py" \\
  --start-date "$START_DATE" \\
  --end-date "$END_DATE"
\`\`\`

This always succeeds or degrades gracefully (warnings go to stderr, never a hard failure) — show
its markdown output as the first section of the combined report.

## Step 3: Run the Linear comments script

Linear auth uses a personal API key from `.env` at the project root. Source it before running the
script:

\`\`\`bash
set -a; source .env; set +a
python3 "<skill-directory>/scripts/gather_linear_comments.py" \\
  --start-date "$START_DATE" \\
  --end-date "$END_DATE"
\`\`\`

- If this exits with code `2` (missing `LINEAR_API_KEY`), skip this section entirely and tell the
  user: "Linear section skipped — `LINEAR_API_KEY` isn't set. Add it to `.env` to include Linear
  comment volume in this report."
- Otherwise, show its markdown output as the second/third sections of the combined report.

## Step 4: Present the combined report

Show both scripts' output together as one report, in this order: PRs Merged, Linear Comments by
Day, Linear Comments by Ticket. If the Linear section was skipped, note why at the top of the
report rather than silently omitting it.

### Optional flags (for other skills)

- `--json` on either script — emit structured JSON instead of markdown, for programmatic use by
  another skill.
- `--no-cache` — force a fresh fetch even if cached.
- `--cache-dir <path>` — override the default cache location.

### Caching

Both scripts cache to `<skill>/cache/` (gitignored). Closed date ranges (end date before today)
cache indefinitely; ranges including today/future expire after 1 hour.
```

- [ ] **Step 2: Manually verify the skill end-to-end**

Invoke the skill:
```
/team-activity 2026-07-10..2026-07-11
```

Expected: one combined markdown report containing a "PRs Merged" table, a "Linear Comments by
Day" table, and a "Linear Comments by Ticket" table, matching the standalone output already
verified in Tasks 1 and 2.

Then verify graceful degradation:
```bash
mv .env .env.bak
```
Invoke `/team-activity 2026-07-10..2026-07-11` again.

Expected: the PRs Merged section still renders correctly; the Linear sections are replaced with a
note that `LINEAR_API_KEY` isn't set. Restore the env file:
```bash
mv .env.bak .env
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/team-activity/SKILL.md
git commit -m "$(cat <<'EOF'
Add team-activity SKILL.md orchestrating PR merges + Linear comments

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
