---
name: eip-billable-hours
description: Logs EIP Points on the Improving Engage portal for billable hours worked, using the "Direct Revenue" category's "40 Billable Hour Week" and "OVER 40 Billable Hour Week" activity types. Pulls actual per-day hours from Workday's "Enter My Time" weekly view rather than assuming a pattern, and correctly splits weeks that straddle an Engage reporting-period (calendar quarter) boundary. Use when the user asks to log EIP points for hours/billable weeks worked, backfill missing EIP billable-hour weeks for a quarter, or reconcile Workday time against Engage points.
user-invocable: true
allowed-tools: Bash, Read
arguments:
  - name: scope
    description: "What to log — a specific week (e.g. 'last week', 'Jun 28 - Jul 4'), or a backfill range/quarter (e.g. 'all of Q2', 'Apr 1 - Jun 30 2026')."
    required: true
  - name: project
    description: "Short label for the work, used in the Notes field (e.g. 'Dragonfly Team extended Python development'). Defaults to whatever project the user has mentioned in the conversation, or asks if unknown."
    required: false
---

# EIP Billable Hours Logger

You log EIP Points for Tonan Salas on the Improving Engage portal (`https://engage.improving.com`) for hours actually worked, based on real data pulled from Workday — never estimated or assumed. The rule Tonan uses: **1 point per 8 billable hours in a week** (a fully-billable 40-hour week is worth a flat 5 points), **plus 1 point per hour worked beyond 40** in that week. Engage models this as two Activity Types under the "Direct Revenue" category:

- **40 Billable Hour Week** — flat 5 points, quantity always 1, logged once per calendar week that was fully billable.
- **OVER 40 Billable Hour Week** — 1 point per unit, quantity = hours worked beyond 40 that week.

Both browser automations reuse the Playwright CLI pattern from `workday-timelogger` and `eip-points`: no MCP browser tools, just `open`/`goto`/`snapshot`/`click`/`select`/`fill` via Bash, with named sessions (`-s=workday`, `-s=engage`) so cookies persist.

## Why this needs real data, not a guess

Weekly hours are not constant — one real week was 11/11/11/8/8 (Mon–Fri) while another was 8/8/8/8/16, with all 8 extra hours landing on a single Friday. Guessing a "typical" week and multiplying by N weeks will misreport both the base-week count and, more importantly, the overtime split. Always pull the actual per-day numbers from Workday first.

## Phase 1: Determine the target weeks

Workday's timesheet weeks run **Sunday–Saturday**. Engage's "Reporting Period" is a **calendar quarter**. These two grids don't line up, which is the crux of this whole skill — see Phase 4.

From the user's `scope`, compute every Sun–Sat week that overlaps the target range, including partial weeks at both ends. A quick Python one-liner is the reliable way to do this — don't count weeks by hand:

```python
import datetime
start = datetime.date(2026, 4, 1)   # target range start
end = datetime.date(2026, 6, 30)    # target range end
d = start
while d.weekday() != 6:  # walk back to the preceding Sunday (Python: Mon=0..Sun=6)
    d -= datetime.timedelta(days=1)
while d <= end:
    print(d, "-", d + datetime.timedelta(days=6))
    d += datetime.timedelta(days=7)
```

## Phase 2: Pull actual hours from Workday

Open Workday and get to the weekly Enter My Time view, following the same login/navigation as `workday-timelogger`:

```bash
npx @playwright/cli@latest -s=workday open "https://wd5.myworkday.com/improving/d/home.htmld" --persistent --headed
```

If redirected to a login page, click the "Single Sign-on" link (SSO usually completes automatically against an already-active session). Navigate to Enter My Time via the "Search Workday" combobox in the banner — click it, then click "Enter My Time" from Recent Searches (or type it in if not present yet).

**Jumping to a target month fast:** don't click "Previous Week" dozens of times for a multi-month backfill. Click the week-range heading (e.g. "Jul 5 – 11, 2026") to open the "Change month and year" calendar popup, click "Previous month"/"Next month" until the target month shows, then click a day in it to jump the whole view there in one step.

**Walking week by week:** once positioned, click "Next Week" repeatedly and read the per-day hours row from each snapshot — it looks like:

```
row "Sun, 4/5 Mon, 4/6 Tue, 4/7 Wed, 4/8 Thu, 4/9 Fri, 4/10 Sat, 4/11 Hours: 0 Hours: 11 Hours: 11 Hours: 11 Hours: 8 Hours: 8 Hours: 0"
```

Record every day's hours for every week in scope — don't just read the weekly Total from the Summary panel, since you need the daily breakdown to handle boundary weeks (Phase 4) and to compute which specific days the overtime hours fell on.

## Phase 3: Compute base + overtime per week

For each week:
- **Total hours** = sum of the 7 days.
- **Base credit** = 5 points if total ≥ 40 (the "40 Billable Hour Week" activity), else flag it — a short week (PTO, holiday, part-time) generally shouldn't get the flat 5 unless the user says otherwise.
- **Overtime hours** = `max(0, total - 40)`, logged 1:1 as "OVER 40 Billable Hour Week" quantity.

## Phase 4: Handle weeks that straddle a quarter boundary

This is the part most likely to go wrong, so slow down here. A Sun–Sat week can span two calendar quarters (e.g. Mon–Tue in Q2, Wed–Fri in Q3). Engage entries are always dated and always belong to whichever quarter the Reporting Period dropdown has selected — there's no way to log "half in Q2, half in Q3" as one entry.

- **Base 5-point credit**: log it exactly **once**, for the whole week, in whichever quarter you and the user agree the week "belongs to" (commonly the quarter containing the Friday, or wherever the majority of the week falls). Logging it in both quarters double-counts a single week of work — don't do this even for convenience.
- **Overtime hours**: these *can* and should be split by the actual calendar days they occurred on. If Monday and Tuesday (Q2) each ran 11 hours (3 extra each = 6 extra) and the Q3 days accounted for the rest of that week's overtime, log 6 extra hours dated in Q2 and the remaining extra hours separately dated in Q3 — each entry's quantity reflects only that quarter's share. Don't attribute a whole week's overtime to a single quarter just because the base credit went there.
- When a boundary week is ambiguous (e.g. it's unclear whether the base credit was already claimed in the adjacent quarter from an earlier session), **stop and ask** rather than guessing — silently claiming a week twice, or in the wrong quarter, is a correctness bug that's hard to spot later. It's fine to present the option to skip a boundary week entirely and let the user decide later.

## Phase 5: Present a confirmation table before touching Engage

Before submitting anything, show the user a table like:

```
| Week (Sun-Sat)   | Mon | Tue | Wed | Thu | Fri | Total | Extra | Notes                              |
|------------------|-----|-----|-----|-----|-----|-------|-------|-------------------------------------|
| Mar 29 - Apr 4    | 11  | 11  | 11  | 8   | 8   | 49    | 9     | Boundary: Mon/Tue are Q1           |
| Apr 5 - 11        | 11  | 11  | 11  | 8   | 8   | 49    | 9     | Fully in Q2                        |
| Apr 26 - May 2    | 8   | 8   | 8   | 8   | 16  | 48    | 8     | All extra hours on Friday          |
```

Call out every boundary week explicitly and state which quarter you plan to credit the base 5 points to, plus how the overtime will be split. Get explicit confirmation before submitting — this is exactly the kind of irreversible-ish, cross-session bookkeeping where a wrong guess is annoying to unwind.

## Phase 6: Log entries on Engage

```bash
npx @playwright/cli@latest -s=engage open "https://engage.improving.com/account/login" --persistent --headed
```

Click "Login with Improving" (OpenIdConnect) — this completes SSO automatically against an active session most of the time. Then go straight to the form:

```bash
npx @playwright/cli@latest -s=engage goto "https://engage.improving.com/app/main/involvement/activity"
```

**Reporting Period always defaults to the current quarter**, even mid-session after a reload or re-login. Every time you land on this page (first load, or after re-authenticating post-timeout), snapshot and re-select the correct quarter in the "Reporting Period" combobox before doing anything else — don't assume it "stuck" from a previous action.

For each entry:
1. Select **Direct Revenue** in the Category combobox.
2. Select **40 Billable Hour Week** or **OVER 40 Billable Hour Week** in the Type combobox (only populates after Category is chosen).
3. Set **Date** (MM/DD/YYYY) to the Friday of that week — or, for a boundary week's split overtime entry, the last day of that week that falls within the quarter you're crediting.
4. Set **Quantity**: leave at 1 for the flat 40-hour type; set to the extra-hours count for the OVER-40 type.
5. Fill **Notes** with a short description, e.g. `"Fully billable week (Apr 5 - Apr 11) - <project>"` or `"9 extra hours worked Apr 5 - Apr 11 - <project>"`.
6. Wait for the **"Add N points"** button to become enabled and show the expected point value — it's disabled until required fields are valid, and the shown value is the live computed result. If it doesn't match what you expect, something's off (wrong type selected, quantity not registered) — don't click through a mismatch.
7. Click it, then re-snapshot and confirm **"Total Points: N"** in the Current Activities summary incremented by the expected amount. This is your source of truth that the submission actually landed — a click can silently no-op if a field wasn't valid.

**Efficiency note**: after a submission, the form resets (Category back to "Select a category…") but the element refs for the Category/Type comboboxes, Date/Quantity/Notes textboxes, and the Add-points button stay valid across many consecutive submissions in the same page session. You don't need to re-snapshot before every field fill — just re-snapshot once after changing Type/Quantity to grab the Add-button's current ref, since its accessible name (and often its ref) changes with the computed point value.

**Session timeouts**: if a snapshot unexpectedly shows a bare login page instead of the form (on either Workday or Engage), the session expired. Re-authenticate (click SSO / "Login with Improving"), navigate back to the target page, and — for Engage — re-select the Reporting Period again, since it resets to the current quarter on every fresh load.

## Phase 7: Final summary

Report, per quarter touched: how many weeks were logged, the base-credit and overtime point totals, the resulting running "Total Points", and any weeks you skipped (short weeks, unresolved boundary-week ambiguity) so the user can follow up later.
