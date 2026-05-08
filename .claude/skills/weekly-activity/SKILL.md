---
name: weekly-activity
description: Gather GitHub activity across all dragonflyic repos for a date range. Use for weekly activity, weekly summary, or when the workday-timelogger agent needs ticket data per day.
user-invocable: true
allowed-tools: Bash
arguments:
  - name: date-range
    description: "Optional date range in YYYY-MM-DD..YYYY-MM-DD format (e.g. 2026-04-01..2026-04-03). Defaults to current week (Monday through today)."
    required: false
---

# Weekly Activity Report

Gather the user's GitHub activity across all `dragonflyic` repos for a date range. The script auto-discovers which repos had activity using the Events API.

## Step 1: Compute Dates

If the user provided a `date-range` argument (e.g. `2026-04-01..2026-04-03`), parse start and end dates from it. Otherwise default to current week (Monday through today):

```bash
# If date-range provided:
START_DATE="<start>"
END_DATE="<end>"

# If no date-range:
START_DATE=$(date -v-Mon +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)
```

## Step 2: Run the Activity Script

The script at `scripts/gather_activity.py` (relative to this skill's directory) handles everything: discovering active repos via the Events API, then per repo fetching commits, authored PRs, issue comments, PR review comments, PR reviews, and authored issues — then deduplicates across repos and outputs a formatted markdown table.

```bash
python3 "<skill-directory>/scripts/gather_activity.py" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE"
```

The script requires `gh` CLI to be authenticated. It will print the full formatted report to stdout.

## Step 3: Present the Output

Show the script's output to the user as-is. If the script reports warnings on stderr, mention them briefly.
