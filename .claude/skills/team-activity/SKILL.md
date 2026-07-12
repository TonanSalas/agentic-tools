---
name: team-activity
description: Report org-wide merged PRs (per PR, with author, plus a per-day Total-vs-you comparison) across all dragonflyic repos, and Linear comment volume (per ticket and author, plus per-day/per-ticket Total-vs-you comparisons) across the whole workspace, for a date range. Use for team activity, team velocity, or communication-volume reports, or to compare your own output against the team total — not for personal-only activity (use weekly-activity for that).
user-invocable: true
allowed-tools: Bash
arguments:
  - name: date-range
    description: "Optional date range in YYYY-MM-DD..YYYY-MM-DD format (e.g. 2026-07-06..2026-07-11). Defaults to current week (Monday through today)."
    required: false
  - name: github-author
    description: "GitHub login to compare against the org-wide PR total. Defaults to tonansalas-dragonfly."
    required: false
  - name: linear-author
    description: "Linear display name to compare against the workspace-wide comment total. Defaults to \"Tonan Salas\"."
    required: false
---

# Team Activity Report

Report two things for a date range, across the whole `dragonflyic` org / Linear workspace, always
alongside a comparison against one person's own contribution:

1. Every merged PR, with its author and URL, plus a per-day/per-repo summary showing the org-wide
   total next to that one person's count (`scripts/gather_pr_merges.py`, `--author` required).
2. Linear comment volume broken down by ticket and author, plus per-day and per-ticket summaries
   showing the workspace-wide total next to that one person's count
   (`scripts/gather_linear_comments.py`, `--author` required).

Both scripts refuse to run without `--author` — there is no team-only mode. The full per-PR and
per-ticket-per-author detail tables still show every author, not just the one being compared;
`--author` only affects the summary/comparison rows.

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

Also resolve the two author identities: use the `github-author`/`linear-author` arguments if
given, otherwise default to `tonansalas-dragonfly` / `Tonan Salas`.

```bash
GITHUB_AUTHOR="<github-author or tonansalas-dragonfly>"
LINEAR_AUTHOR="<linear-author or Tonan Salas>"
```

## Step 2: Run the GitHub PR-merges script

```bash
python3 "<skill-directory>/scripts/gather_pr_merges.py" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE" \
  --author "$GITHUB_AUTHOR"
```

`--author` is required — the script errors without it. It always succeeds or degrades gracefully
otherwise (warnings go to stderr, never a hard failure) — show its markdown output as the first
section of the combined report.

## Step 3: Run the Linear comments script

Linear auth uses a personal API key from `.env` at the project root. Source it before running the
script:

```bash
set -a; source .env; set +a
python3 "<skill-directory>/scripts/gather_linear_comments.py" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE" \
  --author "$LINEAR_AUTHOR"
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
Summary (Total vs `$GITHUB_AUTHOR`), Linear Comments by Ticket and Author, Linear Comments by Day
(Total vs `$LINEAR_AUTHOR`), Linear Comments by Ticket (Total vs `$LINEAR_AUTHOR`). If the Linear
section was skipped, note why at the top of the report rather than silently omitting it.

### Optional flags (for other skills, or for the user)

- `--author <name>` — **required** on both scripts, not optional. It drives the Total-vs-`$AUTHOR`
  comparison columns; it does not hide other authors' rows in the full detail tables. For
  `gather_pr_merges.py`, pass the exact GitHub login, case-insensitive. For
  `gather_linear_comments.py`, pass the exact Linear display name, case-insensitive. This is
  applied after fetching/caching, so the underlying cache always stores the full org-wide result
  regardless of which `--author` was passed.
- `--json` on either script — emit structured JSON instead of markdown, for programmatic use by
  another skill.
- `--no-cache` — force a fresh fetch even if cached.
- `--cache-dir <path>` — override the default cache location.

### Caching

Both scripts cache to `<skill>/cache/` (gitignored). Closed date ranges (end date before today)
cache indefinitely; ranges including today/future expire after 1 hour. The cache always stores the
full, unfiltered result — `--author` filters after reading the cache, so different `--author`
values for the same date range don't trigger separate fetches.
