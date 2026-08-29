---
name: weekly-activity
description: Gather GitHub activity across all dragonflyic repos for a this week, last week or a date range.
---

# Weekly Activity Report

Gather the user's GitHub activity across all `dragonflyic` repos for a date range. The script auto-discovers which repos had activity using the Events API.

## Step 1: Run the Activity Script

Never compute dates yourself. Pick exactly one:

```bash
python3 "<skill-directory>/scripts/gather_activity.py" --range this-week
# or: --range last-week
# or: --start-date "2026-04-01" --end-date "2026-04-03"
```

### Optional flags (for other skills)

- `--json` — emit structured JSON instead of markdown. Each ticket includes `state` (open/closed/unknown), `state_reason`, `is_pr`, `merged`, `days`, `sources`. Use this from `weekly-report` or any caller doing programmatic classification — avoids a per-ticket `gh` round-trip downstream.
- `--no-cache` — force a fresh fetch even if cached.
- `--cache-dir <path>` — override the default cache location.

### Caching

The script caches results to `<skill>/cache/<start>_<end>.json` (gitignored). Cache rules:
- **Closed week** (end-date is before today): cache used indefinitely.
- **Current/future week**: cache used if < 1 hour old.

## Step 2: Present the Output

Create a daily breakdown summary fore each day.
