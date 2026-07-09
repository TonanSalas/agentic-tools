---
name: eip-points
description: Registers an EIP Points activity on the Improving Engage portal by filling and submitting the "Add Activity" form via Playwright CLI browser automation. Use when the user asks to log EIP points, register an EIP activity, add involvement points, or report an EIP activity.
user-invocable: true
allowed-tools: Bash, Read
arguments:
  - name: activity
    description: "Free-text description of the activity to register, e.g. 'Personal Coaching session with Juan about career growth' or 'attended the How to Trust AI key course'. Can also be given as explicit category/type/notes."
    required: true
---

# EIP Points Logger

You automate registering an EIP Points activity for Tonan Salas on the Improving Engage portal (`https://engage.improving.com`). You receive a free-text description of an activity, map it to the closest Activity Category + Activity Type, fill the "Add Activity" form, show a preview, and only submit after the user confirms.

All browser automation uses Playwright CLI via the Bash tool with session `-s=engage`. Use `snapshot` to read the page, then use `click`, `fill`, `select` with element refs from the snapshot output. There are no MCP browser tools.

## Input

The user provides a free-text description of the activity (what they did, when, with whom). From it you must derive:
- **Activity Category** (one of the fixed dropdown options — see below)
- **Activity Type** (depends on the chosen category — always read the live dropdown, never assume)
- **Date** (defaults to today unless the user specifies otherwise)
- **Quantity** (defaults to 1 unless the user specifies a count)
- **Notes** (fill with relevant detail from the user's description — required for some activity types, e.g. "Personal Coaching" needs the name of the other participant)

## Known Activity Categories

`Account Management`, `Business Development`, `Certification/Recognition`, `Come Together`, `Direct Revenue`, `Education/Coaching`, `Improving Cares`, `Improving Path`, `Industry Contribution/Leadership`, `Industry Participation`, `Merger/Acquisition`, `Networking`, `Operations Support`, `Other`, `Recruiting`, `Sales/Marketing Support`, `User Experience`

The Activity Type list is dependent on the category and only appears after selecting it — **always re-snapshot after selecting the category** to read the real options rather than guessing. Example (Education/Coaching): Adjunct Instructor, Client Brown Bag, ImprovingU Attendance, ImprovingU Course Preparation, ImprovingU Group Discussion, ImprovingU Group Discussion Facilitation, ImprovingU Instructor Delivery, ImprovingU Key Course Attendance, ImprovingU Key Course Instructor Delivery, ImprovingU Key Course Student Work, ImprovingU Planning, ImprovingU Remote Facilitation, Personal Coaching, Project Review Presentation.

If the user's description doesn't clearly map to one category/type, pick your best match and call it out in the preview so the user can correct it before confirming.

## Phase 1: Launch Browser & Login

Always open the login URL first:
```bash
npx @playwright/cli@latest -s=engage open "https://engage.improving.com/account/login" --persistent --headed
```

Snapshot the page. If the login form is shown ("Login with Improving" button), click it — SSO with an already-active Microsoft session usually completes automatically. If it lands on an interactive Microsoft login/MFA prompt instead, tell the user to complete it in the visible Chrome window and wait for their confirmation before proceeding.

Once logged in, the URL redirects to `/app/main/dashboard/employee-home`.

## Phase 2: Navigate to the Activity Form

Navigate directly by URL (don't rely on clicking sidebar links — the sidebar drawer overlay can intercept clicks):
```bash
npx @playwright/cli@latest -s=engage goto "https://engage.improving.com/app/main/involvement/activity"
```

Snapshot — SPA pages sometimes render empty on the first snapshot right after navigation; if so, snapshot again after a short pause. Confirm the "Add Activity" panel is visible with the Activity Category dropdown.

## Phase 3: Fill the Form

1. **Select Activity Category** using `select` on the category combobox with the best-matching option from the Known Categories list above.
2. **Snapshot** to read the now-populated Activity Type dropdown (its options are injected dynamically per category).
3. **Select Activity Type** matching the user's description as closely as possible. If a type's description text (shown near the form once selected) implies required info (e.g. naming a participant), make sure Notes covers it.
4. **Date**: leave as today's default unless the user specified a different date — fill the Date textbox in `MM/DD/YYYY` format if it needs to change.
5. **Quantity**: leave as 1 unless the user specified a different count.
6. **Notes**: fill with a concise note built from the user's description (names, topic, context).
7. Snapshot once more — the "Add N points" button shows the live computed point value and enables once the form is valid (category + type + notes-if-required all filled). If it's still disabled, something required is missing — check the type's description text and fill accordingly.

## Phase 4: User Review & Confirm

Do **not** click "Add N points" yet. Present a preview to the user:

```
## EIP Activity Preview

| Field    | Value                                  |
|----------|-----------------------------------------|
| Category | Education/Coaching                      |
| Type     | Personal Coaching                       |
| Date     | 07/02/2026                              |
| Quantity | 1                                        |
| Notes    | Coaching session with Juan about career growth |
| Points   | +3 pts                                  |
```

Ask: **"¿Confirmas que registre esta actividad? Dime si algo debe cambiar, o 'aprobado' para enviarla."**

If the user requests changes, update the relevant field(s) (re-select dropdowns / re-fill as needed) and present the preview again.

## Phase 5: Submit

Once the user approves, click the "Add N points" button. Snapshot to confirm the activity now appears in the "Current Activities" table for the current reporting period with the expected Category/Type/Date/Quantity/Points, and that "Total Points" updated accordingly.

## Phase 6: Final Summary

1. Close the browser: `npx @playwright/cli@latest -s=engage close`
2. Report the final status: category, type, points added, and new running total for the quarter (visible in the "Current Activities" table's "Total Points" header).

## Error Handling

- **Blank snapshot right after navigation**: SPA render delay — snapshot again.
- **Click intercepted by `drawer-overlay`**: the sidebar menu is open and blocking clicks; prefer `goto` with the direct URL over clicking sidebar links, or close the sidebar drawer first.
- **"Add N points" stays disabled**: a required field is missing — re-check the Activity Type's description text for required Notes content (e.g. participant names).
- **Wrong reporting period**: if the target date falls outside the current quarter, use the "Reporting Period" dropdown to switch quarters before verifying the activity landed in Current Activities.
- **Session expired**: re-open `https://engage.improving.com/account/login` to re-authenticate, then repeat from Phase 2.
