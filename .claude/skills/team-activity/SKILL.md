---
name: team-activity
description: Report org-wide merged PRs (per PR, with author, plus per-day/per-repo totals) across all dragonflyic repos, and Linear comment volume (per ticket and author, plus per-day/per-ticket totals) across the whole workspace, for a date range. Use for team activity, team velocity, or communication-volume reports — not for personal activity (use weekly-activity for that).
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

1. Every merged PR, with its author and URL, plus a per-day/per-repo summary
   (`scripts/gather_pr_merges.py`).
2. Linear comment volume broken down by ticket and author, plus per-day and per-ticket summaries
   (`scripts/gather_linear_comments.py`).

Author columns exist so PRs/comments can be attributed to a specific person — don't assume every
row belongs to the user who invoked the skill; always check the Author column before claiming an
item as theirs.

> **Performance note**: This skill just runs two Python scripts and prints their output — no
> reasoning needed. When invoking it non-interactively from another skill, prefer launching via
> the `Agent` tool with `model: "claude-haiku-4-5-20251001"` to save tokens.

## Step 1: Compute dates

If the user provided a `date-range` argument, parse start and end dates from it. Otherwise
default to the current week (Monday through today):

```bash
# If date-range provided:
START_DATE="<start>"
END_DATE="<end>"

# If no date-range:
START_DATE=$(date -v-Mon +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)
```

If the range spans more than 90 days, tell the user this may be slow (org-wide PR search and
per-comment Linear pagination both scale with range size) and confirm before proceeding.

## Step 2: Run the GitHub PR-merges script

```bash
python3 "<skill-directory>/scripts/gather_pr_merges.py" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE"
```

This always succeeds or degrades gracefully (warnings go to stderr, never a hard failure) — show
its markdown output as the first section of the combined report.

## Step 3: Run the Linear comments script

Linear auth uses a personal API key from `.env` at the project root. Source it before running the
script:

```bash
set -a; source .env; set +a
python3 "<skill-directory>/scripts/gather_linear_comments.py" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE"
```

- If this exits with code `2` (missing `LINEAR_API_KEY`), skip this section entirely and tell the
  user: "Linear section skipped — `LINEAR_API_KEY` isn't set. Add it to `.env` to include Linear
  comment volume in this report."
- Otherwise, show its markdown output as the second/third sections of the combined report.

## Step 4: Present the combined report

Emit a top-level header with the date range, then both scripts' output together as one report:

```
## Team Activity: $START_DATE - $END_DATE
```

followed by, in this order: PRs Merged (full per-PR list with author/URL), PRs Merged — Daily
Summary, Linear Comments by Ticket and Author, Linear Comments by Day, Linear Comments by Ticket.
If the Linear section was skipped, note why at the top of the report rather than silently
omitting it.

### Optional flags (for other skills, or for the user)

- `--author <name>` on either script — filter results to one person, applied after fetching/
  caching so the underlying cache stays the full org-wide result. For `gather_pr_merges.py`, pass
  the exact GitHub login (e.g. `tonansalas-dragonfly`), case-insensitive. For
  `gather_linear_comments.py`, pass the exact Linear display name (e.g. `Tonan Salas`),
  case-insensitive. If the user asks "which of these are mine" or similar, re-run both scripts
  with `--author` set to their identity rather than eyeballing the Author column.
- `--json` on either script — emit structured JSON instead of markdown, for programmatic use by
  another skill.
- `--no-cache` — force a fresh fetch even if cached.
- `--cache-dir <path>` — override the default cache location.

### Caching

Both scripts cache to `<skill>/cache/` (gitignored). Closed date ranges (end date before today)
cache indefinitely; ranges including today/future expire after 1 hour. The cache always stores the
full, unfiltered result — `--author` filters after reading the cache, so different `--author`
values for the same date range don't trigger separate fetches.
