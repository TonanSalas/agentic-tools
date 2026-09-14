---
name: weekly-activity
description: Gather GitHub activity across all dragonflyic repos for a this week, last week or a date range.
---

# Weekly Activity Report

## Task

Run `gather_activity.py`, then write a summary of what the user did during that period.

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

Reply with exactly this YAML and nothing else. One `days` entry per date in the range.

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
summary: |
  <html>
  <b>TEC Weekly Status Report – Dragonfly</b><br>
  <b>Project:</b> Dragonfly<br>
  <b>Date:</b> <!-- today's date, spelled out: April 11, 2026 --><br>
  <b>Status:</b> <!-- 🟢 default · 🟡 notable risk · 🔴 critical blockers only --><br>
  <br>
  <b>Summary</b><br>
  <!-- 2–4 sentences giving a high-level picture -->
  <br>
  <b>Accomplished</b>
  <ul>
  <!-- One <li> per ticket that is done. Rephrase raw titles into clear standalone accomplishments. Collapse 2+ tickets from the same effort into one line. Name the work, not the ticket. -->
  </ul>
  <b>Planned Activities</b>
  <ul>
  <!-- One <li> per remaining ticket — open PRs, open issues. Name the work, not the ticket. A ticket may also appear in Accomplished if partially closed but reopened for remaining work. -->
  </ul>
  <b>Risks</b><br>
  <!-- Risks apparent from the data: blocked items, open security issues, critical blockers. If nothing stands out, write exactly: No risks identified at the moment. -->
  <!-- Shoutouts: append `<br><br><b>Shoutouts</b><br>` and the text ONLY if the user explicitly mentioned a shoutout. Never fabricate one — omit the block entirely. -->
  </html>
```
