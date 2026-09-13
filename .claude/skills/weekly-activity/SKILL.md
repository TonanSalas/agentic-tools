---
name: weekly-activity
description: Gather GitHub activity across all dragonflyic repos for a this week, last week or a date range.
---

# Weekly Activity Report

## Task

Run `gather_activity.py`, then write a day-by-day summary of what the user did during that period.

## Context

The script owns date resolution and always emits structured JSON (each ticket
includes `state`, `state_reason`, `is_pr`, `merged`, `days`, `sources`) — it
auto-discovers which `dragonflyic` repos had activity using the Events API.
Never compute dates yourself. Pick exactly one form:

```bash
python3 "<skill-directory>/scripts/gather_activity.py" --range this-week
# or: --range last-week
# or: --start-date "2026-04-01" --end-date "2026-04-03"
```

## Output format

Reply with exactly this YAML and nothing else. One `days` entry per date in the
range.

```yaml
range:
  start: 2026-08-10
  end: 2026-08-14
days:
  - date: 2026-08-10
    items:
      - ref: insurance_portal#59
        title: Serve real captured quote documents per line
      - ref: agentic-org#1468
        title: Move carrier capture kits to Google Drive
    summary: One sentence on the shape of this day's work, drawn only from the items above.
  - date: 2026-08-11
    items: []
    summary: Quiet day — no recorded activity.
```
