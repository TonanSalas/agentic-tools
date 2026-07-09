# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Claude Code skills workspace for automating weekly workflows at Improving
— primarily Workday time entry and GitHub activity reporting. There is no build system, test suite, or application code. The repo contains only skill definitions and supporting scripts.

## Skills

- `/workday-timelogger` — Automates Workday time entry. Gathers GitHub activity, builds an entry plan (two tables: Workday entries + referenced issues), then fills the Workday timesheet via Playwright CLI browser automation. Usage: `/workday-timelogger "Mon 11, Tue 8, Wed 8, Thu 8, Fri 5"`
- `/weekly-activity` — Gathers GitHub activity across all `dragonflyic` repos for a date range. Runs `gather_activity.py` which auto-discovers repos via the GitHub Events API. Usage: `/weekly-activity 2026-04-07..2026-04-11`
- `/workday-edge-login` — Opens Workday in a real Microsoft Edge window with CDP remote debugging, attaches Playwright over CDP (session `-s=workday-edge`), logs in via interactive SSO, and stops on the Enter My Time page. Login/navigation only (no time entry). Usage: `/workday-edge-login`
- `/eip-points` — Registers an EIP Points activity on the Improving Engage portal (`https://engage.improving.com`). Maps a free-text activity description to Category + Type, fills the "Add Activity" form via Playwright CLI (session `-s=engage`), previews the computed points, and submits only after user confirmation. Usage: `/eip-points "Personal Coaching session with Juan about career growth"`
- `/eip-points-invite` — Generates a shareable EIP Points "Add Activity" link for a meeting (fills the Engage form and clicks "Copy Link" instead of submitting) and sends it to a Teams chat via the `teams-messenger` skill so attendees can self-register. Chains `eip-points`' form-fill logic with `teams-messenger`'s send flow. Usage: `/eip-points-invite "AIR for non developers"`
- `/eip-billable-hours` — Logs EIP Points for billable hours worked, using the "Direct Revenue" category's "40 Billable Hour Week" (flat 5 pts) and "OVER 40 Billable Hour Week" (1 pt/hr) activity types. Pulls actual per-day hours from Workday rather than assuming a pattern, and correctly splits weeks that straddle an Engage reporting-period (quarter) boundary. Usage: `/eip-billable-hours "backfill Q2" "Dragonfly Team extended Python development"`

## Browser Automation

All browser automation uses Playwright CLI (`npx @playwright/cli@latest`) via Bash — no MCP browser tools. Key patterns:

- Named sessions: `-s=workday` isolates the browser session
- `--persistent --headed` flags: preserves login cookies and keeps the browser visible
- Element refs (e.g., `e5`, `e12`) come from `snapshot` output and are used in `click`, `fill`, `select` commands
- SSO login is interactive — the user completes auth manually in the Chrome window

### CDP attach to Edge (workday-edge-login)

The `workday-edge-login` skill drives a real **Microsoft Edge** instead of Playwright's Chromium. Edge is launched with `--remote-debugging-port` on a dedicated `--user-data-dir` (`~/.edge-cdp-debug`) because Edge/Chromium 136+ block remote debugging on the *default* profile dir. The dedicated dir is seeded once from the real Edge profile (carries the Improving tenant), and lets the debug Edge coexist with the user's normal browsers. Playwright attaches with `attach --cdp=http://localhost:9333`. Use `detach` (not `close`) to release the session while leaving Edge open.
