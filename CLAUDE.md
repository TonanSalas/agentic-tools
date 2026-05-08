# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Claude Code skills workspace for automating weekly workflows at Improving
— primarily Workday time entry and GitHub activity reporting. There is no build system, test suite, or application code. The repo contains only skill definitions and supporting scripts.

## Skills

- `/workday-timelogger` — Automates Workday time entry. Gathers GitHub activity, builds an entry plan (two tables: Workday entries + referenced issues), then fills the Workday timesheet via Playwright CLI browser automation. Usage: `/workday-timelogger "Mon 11, Tue 8, Wed 8, Thu 8, Fri 5"`
- `/weekly-activity` — Gathers GitHub activity across all `dragonflyic` repos for a date range. Runs `gather_activity.py` which auto-discovers repos via the GitHub Events API. Usage: `/weekly-activity 2026-04-07..2026-04-11`

## Browser Automation

All browser automation uses Playwright CLI (`npx @playwright/cli@latest`) via Bash — no MCP browser tools. Key patterns:

- Named sessions: `-s=workday` isolates the browser session
- `--persistent --headed` flags: preserves login cookies and keeps the browser visible
- Element refs (e.g., `e5`, `e12`) come from `snapshot` output and are used in `click`, `fill`, `select` commands
- SSO login is interactive — the user completes auth manually in the Chrome window
