---
name: workday-timelogger
description: Logs weekly time into Workday by gathering GitHub activity via the weekly-activity skill, then automating the Workday Enter My Time UI via Playwright CLI. Use when the user asks to log time, fill timesheet, or enter hours into Workday.
user-invocable: true
allowed-tools: Bash, Skill, Read, Write, Edit
arguments:
  - name: hours
    description: "Hours per day, e.g. 'Mon 11, Tue 8, Wed 8, Thu 8, Fri 5'"
    required: true
  - name: project
    description: "Workday project name for the Time Type dropdown (e.g. 'Dragonfly' or 'Dragonfly: Team extended- Python development'). Defaults to 'Dragonfly'."
    required: false
---

# Workday Time Logger

You automate time entry into Workday for Tonan Salas. You receive hours per day and a project name, gather ticket activity from GitHub, then fill in the Workday timesheet via browser automation.

All browser automation uses Playwright CLI via the Bash tool with session `-s=workday`. Use `snapshot` to read the page, then use `click`, `fill`, `type`, `select`, `press` with element refs from the snapshot output. There are no MCP browser tools.

## Input Parameters

The user provides:
- **Hours per day**: e.g., "Mon 11, Tue 8, Wed 8, Thu 8, Fri 5"
- **Project name**: The Workday project to search for in the Time Type dropdown (e.g., "Dragonfly" or "Dragonfly: Team extended- Python development")

Constraints:
- Max 8 regular hours per day (first entry)
- Max 3 extra hours per day (second entry)
- Max 11 total hours per day

## Phase flags (harness mode)

The `weekly-log` harness calls this skill one phase at a time. When the invocation carries one of these flags, do only that phase, write the named output file, and stop. Do not ask the user anything in harness mode.

- `--plan-only --hours "..." --week-start YYYY-MM-DD [--activity FILE] --out FILE`: Phase 2 only. Run `plan_entries.py` with those arguments, print the two tables, and stop. No browser.
- `--enter-only PLAN --out FILE`: Phases 3–6 driven by the plan JSON at `PLAN`. Afterwards read the per-day hour totals from the Enter My Time header row, save a screenshot to `.playwright-mcp/<week_start>.png`, and write `{"entries":[{"date","entry","hours","status"}],"totals":{"YYYY-MM-DD": hours},"screenshot": path}` to `--out`, where `status` is one of `Entered`, `Already filled`, `Locked`, `Error`. Do NOT click Review or Submit.
- `--submit-only`: Phase 7 step 6 only. The browser session `-s=workday` is already on the Enter My Time weekly view. Click Review, snapshot, then click Submit by role selector (`click 'role=button[name="Submit"]'`), verify, and stop. If that click is blocked by the sentinel hook, report the hook's message verbatim and stop — never retry with a ref, coordinates, or any other selector.

## Phase 1: Gather Activity

Derive the date range from the user's input (Monday of the week through the latest day named), then **clamp the end date to today** — there is no GitHub activity for future days. Call the `/weekly-activity` skill using the Skill tool with the clamped range:

```
skill: "weekly-activity", args: "2026-03-30..2026-04-03"
```

Save the YAML it returns verbatim to `.playwright-mcp/activity-<week_start>.yaml` (or use the `--activity` file when one is given). If every requested day is in the future, skip the activity call and pass no `--activity` file; the planner writes `Activity placeholder` comments for those days.

## Phase 2: Plan Entries

Never do the split, ticket-distribution or comment arithmetic yourself. Run the planner:

```bash
python3 "<skill-directory>/scripts/plan_entries.py" \
  --hours "Mon 11, Tue 8, Wed 8, Thu 8, Fri 5" \
  --week-start 2026-03-30 \
  --activity .playwright-mcp/activity-2026-03-30.yaml \
  --today 2026-04-05 \
  --out .playwright-mcp/plan-2026-03-30.json
```

The script encodes the rules (tested in `tests/test_plan_entries.py`):

1. Hours > 8 are split into a `Reg` entry (8) and an `Extra` entry (remainder, max 3).
2. Tickets are distributed proportionally: `Reg` gets `ceil(n * 8 / total)`, `Extra` the rest; a single ticket goes in both.
3. `(unknown #N)` titles are dropped — unresolved cross-repo references, not work items.
4. Comments are `ref: title, ref: title`; if that exceeds 255 chars, refs only.
5. Days after today, or past days with no items, get the comment `Activity placeholder`.

Render the plan JSON as **exactly these two tables, with these column headers**, and confirm with the user before proceeding (skip the confirmation in harness mode).

**Table 1 — Workday Entries** (one row per plan entry, so days >8h get two rows):
```
| Day       | Entry | Hours | Comment                                    |
|-----------|-------|-------|--------------------------------------------|
| Mon 04/01 | Reg   | 8     | ao#123: Fix auth token, ao#456: Update API |
| Mon 04/01 | Extra | 3     | ao#789: Refactor broker service            |
| Tue 04/02 | Reg   | 8     | ao#456: Update API, ao#790: Add tests      |
| Wed 04/03 | Reg   | 8     | Activity placeholder                       |
```

**Table 2 — Issues Referenced** (the plan's `issues` list):
```
| Issue  | Title                   |
|--------|-------------------------|
| ao#123 | Fix auth token          |
| ao#456 | Update API              |
| ao#789 | Refactor broker service |
| ao#790 | Add tests               |
```

## Phase 3: Launch Browser & Login

**Always open the home URL first, never the Enter My Time URL directly.** Hitting `/d/task/2998$10895.htmld` while unauthenticated returns a confusing error page; the home URL cleanly redirects to login when needed.

Open a persistent, headed browser session pointing to the Workday home page:
```bash
npx @playwright/cli@latest -s=workday open "https://wd5.myworkday.com/improving/d/home.htmld" --persistent --headed
```

Snapshot the page to check login state. If redirected to a login page, click the "Single Sign-on" link. If SSO requires manual authentication (Okta, Azure AD, etc.), tell the user to complete it in the Chrome window and wait for confirmation.

Once logged in (page title is "Workday improving" and the home dashboard is visible), navigate to Enter My Time via the **Search Workday** combobox in the top banner.

**Two rules that prevent the most common self-inflicted failures (both seen in real runs):**

1. **NEVER open a deep-link task URL** (e.g. `/d/task/2998$10895.htmld`). Even when you are already logged in, deep-linking drops you onto a fresh Microsoft SAML sign-in page that asks for a username, and you will wrongly conclude "login required". Always reach Enter My Time by clicking inside the app (Search combobox → result). If you ever land on a `login.microsoftonline.com` or `wd5-identity` page *after* having reached the dashboard, you broke the session by navigating away — go back to `https://wd5.myworkday.com/improving/d/home.htmld` (the home URL only) and click the "Single Sign-on" link once.

2. **The "Menu" / "Shortcuts" side dialog after login is rendered off-screen (negative x) and is inert — it does NOT actually block clicks.** Do not waste turns pressing Escape, clicking its Close/X, or clicking "Menu" to dismiss it. Ignore it: take one fresh `snapshot`, then click the **Search Workday** combobox by its *current* ref, type `enter my time`, and click the "Enter My Time" result.

1. Click the "Search Workday" combobox in the banner.
2. Snapshot — if "Enter My Time" already appears in the dropdown under **Recent Searches** (it will after the first run, since the persistent session retains history), click it directly. Otherwise type `enter my time` to trigger the search dropdown.
3. Snapshot — the dropdown shows a clickable "Enter My Time" task result. Click it by ref.
4. Verify the "Enter My Time" heading is visible (page title becomes "Enter My Time - Workday").

## Phase 4: Navigate to Correct Week

Snapshot the weekly view and check the displayed week range (e.g., "Mar 29 – Apr 4, 2026"). If the target week doesn't match, click the Previous/Next Week buttons until the correct week is shown. Verify with another snapshot before proceeding.

## Phase 5: Check Existing Entries

Snapshot the weekly view and examine each target day:
- If hours are already entered, skip that day ("Already filled")
- If "Time Period Lockout" or "Edit Prevented by Project Billing" is shown, skip that day ("Locked")

**Heads up on holiday auto-reclassification:** after submission, Workday may rewrite a Dragonfly entry that lands on a Mexican holiday into `Mexico PTO – Time Track / Project > Holiday Swap`. Hour totals stay correct (it stays counted as Project Time, not Time Off) — the label change is expected, not a failed submission.

## Phase 6: Enter Time

For each day that needs entries:

### Opening the Enter Time Dialog

The empty day column area in Workday is not a named element in the accessibility tree — you cannot click it by ref. Three things to know:

1. **Calibrate column centers per week.** The calendar shows Sun–Sat (Mon is the *2nd* column, not the 1st). Run an `eval` once per week to read every day-header bounding box and store the center x-coordinates:
   ```js
   const days = ['Sun, M/D','Mon, M/D','Tue, M/D','Wed, M/D','Thu, M/D','Fri, M/D','Sat, M/D'];
   // ...substitute the actual dates for the displayed week, then for each label
   //    find the leaf element matching it and return r.x + r.width/2
   ```
   Reuse those x values for every click in that week. Y around 500 in the empty column reliably opens the dialog.

2. **Use real mouse events.** DOM `el.click()` is silently swallowed by Workday's handlers. Instead:
   ```bash
   npx @playwright/cli@latest -s=workday mousemove <x> <y>
   npx @playwright/cli@latest -s=workday mousedown
   npx @playwright/cli@latest -s=workday mouseup
   ```
   Then snapshot — page title flips to "Enter Time - Workday" when the dialog opened.

3. **Side-panel after SSO blocks the first click.** After login a "Menu / Shortcuts" side dialog often stays open and intercepts clicks. Pressing Escape and clicking its X button both fail. The reliable dismissal is to click the "Enter My Time" heading once before any column click.

**Do NOT** use the "Actions" button or "Quick Add" menu — always click the day column directly.

### Filling the Form

1. **Time Type**: Click the Time Type field. **Typing in it does not filter** — the dropdown only shows submenus (Most Recently Used / Project Plan Tasks / Time Entry Codes / Absence). Navigate by clicking:
   - For project work (e.g. Dragonfly): **Most Recently Used → Dragonfly: Team extended- Python development**.
   - For PTO: **Absence → Paid Time Off**. Selecting PTO auto-fills Hours to 8 and the Comment is optional.
   To navigate from a leaf back to the parent submenu, press `ArrowLeft`.
2. **Re-snapshot before filling Hours/Comment**: the Hours and Comment refs change after you select a Time Type option. Don't reuse refs from before the selection.
3. **Hours**: Fill the hours field with the entry's hours (e.g., "8").
4. **Comment**: Fill the comment field with the ticket string (e.g., "#123: Fix auth, #456: Update API"). Workday's comment field accepts at least 255 characters — the compact ticket-numbers format (e.g. `ao#548, ao#605, ao#606, ...`) fits easily even for 9-ticket days.
5. **Submit**: Click OK. Snapshot to verify the entry was created (the day's Hours total in the header row updates).

If there's an error, take a screenshot and report it.

### Tool-call optimization

A naive entry takes ~12 tool calls (snapshot → click Time Type → snapshot → click MRU → snapshot → click Dragonfly radio → snapshot → fill Hours → fill Comment → click OK → snapshot). You can cut this roughly in half by:

1. **Chain idempotent actions in one Bash call** using `&&` when refs don't change between them:
   - `mousemove X Y && mousedown && mouseup` (opens the day dialog in one call)
   - `fill <hours-ref> "8" && fill <comment-ref> "..." && click <ok-ref>` (submit in one call)
2. **Skip exploratory snapshots when the next click target's accessible name is stable**. After clicking Time Type, the role-name selectors `'option "Submenu Most Recently Used"'` and `'option "Dragonfly: Team extended- Python development"'` (or its child `radio`) are reliable — try clicking by name first, only snapshot if it fails.
3. **Snapshot once per dialog state, not once per click**. The form refs (Time Type / Hours / Comment / OK) are all valid until the Time Type selection mutates the form. After selecting the time type, snapshot once to capture the new Hours/Comment refs — they're stable until OK is clicked.

After the first day's entry of the week, Dragonfly is the top item in the Most Recently Used list, so the flow is the same for every Dragonfly entry.

### Extra Hours Entry

If the day has extra hours (>8), open a new Enter Time dialog on the same day column and repeat the form fill with the remaining hours and tickets.

## Phase 7: User Review & Submit

After all entries are entered:

1. Navigate back to the Enter My Time weekly view.
2. Take a screenshot of the weekly view.
3. Present the summary table to the user and ask them to review the entries in the browser:

```
## Time Entry Summary

| Day       | Entry | Hours | Comment                              | Status   |
|-----------|-------|-------|--------------------------------------|----------|
| Mon 04/01 | Reg   | 8     | #123: Fix auth, #456: Update API     | Entered  |
| Mon 04/01 | Extra | 3     | #789: Refactor broker                | Entered  |
| Tue 04/02 | Reg   | 8     | #456: Review, #790: Add tests        | Entered  |
| Wed 04/03 | -     | -     | -                                    | Locked   |
| Thu 04/04 | Reg   | 8     | Activity placeholder                 | Entered  |

Total hours entered: 27
Days completed: 3/4
```

4. Ask the user: **"Please review the entries in the browser. Let me know if anything needs to be changed, or say 'approved' to submit."**
5. If the user requests changes, make the corrections (click the entry to edit, update fields, save) and repeat from step 2.
6. Once the user approves, click the **Review** button on the weekly view, snapshot to confirm the review/submit dialog, and click **Submit** by role selector — `npx @playwright/cli@latest -s=workday click 'role=button[name="Submit"]'` (or `name="Confirm"` if that is what Workday shows). Prefer the role selector over a ref: the repo's sentinel hook recognises the committing click by its name (it also resolves refs against the latest snapshot). Verify the submission succeeded with a final snapshot.

## Phase 8: Final Summary

After submission is confirmed:

1. Close the browser.
2. Report the final status — total hours submitted, days completed, and any entries that were skipped or had errors.

## Error Handling

- **Dialog doesn't open**: Try clicking at different areas in the day column.
- **Time Type not found**: Try shorter search terms. Ask the user if the project name is correct.
- **Submission error**: Screenshot, skip the entry, continue with next day, report in summary.
- **Session timeout**: Navigate back to the home URL (`https://wd5.myworkday.com/improving/d/home.htmld`) to re-authenticate cleanly, then re-open Enter My Time via the shortcut. Don't navigate directly to the Enter My Time URL while logged out — it errors instead of redirecting to login.
- **Already filled**: Skip and report as "Already filled".
