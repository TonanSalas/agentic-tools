# agentic-tools

A Claude Code workspace with skills for automating weekly workflows — time logging, activity reporting, and browser automation via Playwright.

## Skills

### `/workday-timelogger`

Automates time entry into Workday. Gathers GitHub activity via the `weekly-activity` skill, builds an entry plan with two tables (Workday entries + referenced issues), then fills in the Workday timesheet using browser automation.

**Usage:**
```
/workday-timelogger "Mon 11, Tue 8, Wed 8, Thu 8, Fri 5"
```

### `/weekly-activity`

Gathers GitHub activity across all `dragonflyic` repos for a date range. Returns a day-by-day breakdown of commits, PRs, and issues.

**Usage:**
```
/weekly-activity 2026-04-07..2026-04-11
```

## Browser Automation

The `workday-timelogger` skill uses Playwright CLI (`npx @playwright/cli@latest`) for browser automation. Each action (navigate, click, fill, snapshot) is a separate Bash call with a named session (`-s=workday`). The `--persistent` flag preserves login sessions across runs.

## Prerequisites

- `gh` CLI authenticated for GitHub activity gathering
- Google Chrome installed for browser automation
- Playwright CLI: `npx @playwright/cli@latest`
