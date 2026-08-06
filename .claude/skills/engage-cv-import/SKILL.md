---
name: engage-cv-import
description: Parses a CV (PDF or DOCX) and populates the Improving Engage profile's Experience, Education, and Certification & Exam sections via Playwright CLI browser automation, skipping anything already saved and asking before adding anything new. Use when the user asks to import their CV/resume into Engage, sync their CV to their Engage profile, or update their Engage profile from their resume.
user-invocable: true
allowed-tools: Bash, Read
arguments:
  - name: cv_path
    description: "Absolute path to the CV file to import, PDF or DOCX."
    required: true
---

# Engage CV Import

You take a CV file, extract Experience/Education/Certification & Exam entries from it,
compare them against what's already saved on the user's Improving Engage profile
(`https://engage.improving.com`), and — only after the user confirms — fill in the new
entries via the Profile forms.

All browser automation uses Playwright CLI via the Bash tool with session `-s=engage`. Use
`snapshot` to read the page, then `click`/`fill`/`select` with element refs from the snapshot
output. Refs regenerate every snapshot — never reuse a ref from an earlier snapshot or from
this document.

## Input

`cv_path` — absolute path to a PDF or DOCX CV file.

## Phase 1: Launch Browser & Login

```bash
npx @playwright/cli@latest -s=engage open "https://engage.improving.com/account/login" --persistent --headed
```

Snapshot. If the login form is shown, click "Login with Improving" — SSO with an active
Microsoft session usually completes automatically. If it lands on an interactive
Microsoft login/MFA prompt instead, tell the user to complete it in the visible Chrome window
and wait for confirmation. Once logged in, the URL redirects to
`/app/main/dashboard/employee-home`.

Snapshot and find the "Profile" nav link's `href` (e.g.
`/app/main/profile/skills-strengths?userId=28003`) — extract the `userId` query param. Every
Profile URL in the phases below needs this value; never hardcode one.

## Phase 2: Read Current Profile

```bash
npx @playwright/cli@latest -s=engage goto "https://engage.improving.com/app/main/profile/experience?userId=<id>"
```

Snapshot (re-snapshot if blank — SPA render delay right after navigation). Record each
existing Experience entry's Company, Title, Start Date, End Date.

```bash
npx @playwright/cli@latest -s=engage goto "https://engage.improving.com/app/main/profile/education?userId=<id>"
```

Snapshot. This page has two subsections — record both:
- **Certification & Exam**: Certification Name, Organization
- **Education**: School/Institution, Degree, Start Date, End Date

This baseline is what Phase 4 deduplicates against.

## Phase 3: Extract Data From the CV

- **PDF**: read `cv_path` directly with the `Read` tool.
- **DOCX**: run
  ```bash
  python3 "<skill-directory>/scripts/extract_docx_text.py" "<cv_path>"
  ```
  then work from that printed text (or use `--out <tmp-path>` and `Read` the result).

From the text, derive three structured lists:

| Section | Fields to extract |
|---|---|
| Experience | Company, Title, Summary/description, Start Date, End Date |
| Education | School/Institution, Degree, Start Date, End Date |
| Certification & Exam | Certification Name, Organization, Exam Date, Expiration Date (if stated), Certification Number (if stated), Verification URL (if stated) |

## Phase 4: Deduplicate

See `references/parsing.md`'s "Deduplication matching rule". For each extracted entry,
compare against the Phase 2 baseline and mark it:

- **New** — no match, will be proposed for addition
- **Already exists** — matched an existing entry, will be skipped; never re-added or
  overwritten

## Phase 5: Ask About Rewriting Descriptions

If at least one **New** Experience entry has a Summary/description, ask the user:

> "¿Quieres que mejore la redacción de tus descripciones de experiencia según buenas
> prácticas de reclutamiento (fórmula PAR, verbos de acción, resultados en primer plano)?
> No voy a inventar cifras ni logros que no estén ya en tu CV — solo mejoro cómo están
> dichos. Se mantiene en inglés."

If yes: read `references/resume-best-practices.md` and rewrite each such entry's Summary
following its rules — most importantly, its "one hard rule" (never introduce a number, scope,
or outcome absent from the source). If no: use the extracted text as-is.

This step only applies to Experience Summaries — Education and Certification entries are
factual fields with no narrative text to rewrite.

## Phase 6: Preview & Confirm

Present one combined table covering every extracted entry, grouped by section:

```
## Engage Profile Import Preview

### Experience
| Status | Company | Title | Dates | Summary |
|--------|---------|-------|-------|---------|
| Nuevo | Acme Corp | Backend Engineer | 01/2022 - Present | Optimized Redis caching... |
| Ya existe — se omite | Dragonfly | Consultant | 2023 - Present | — |

### Education
| Status | School | Degree | Dates |
|--------|--------|--------|-------|
| Nuevo | State University | B.S. Computer Science | 2018 - 2022 |

### Certification & Exam
| Status | Name | Organization | Exam Date | Type |
|--------|------|---------------|-----------|------|
| Nuevo | AWS Certified Solutions Architect | Amazon Web Services | 03/2024 | Professional |
| Falta un dato | Scrum Master | Scrum Alliance | ⚠ no exam date in CV | — |
```

For any entry tagged "Falta un dato", ask the user to supply the missing value or say to drop
that entry — never guess it. Ask:

**"¿Confirmas que agregue las entradas marcadas 'Nuevo'? Dime si algo debe cambiar, o
'aprobado' para continuar."**

If the user requests changes (edit a field, drop an entry), update and re-present the table.

## Phase 7: Fill Forms

Only entries confirmed as **New** in Phase 6 get filled — never a "Ya existe" or unresolved
"Falta un dato" entry.

### Experience

Navigate to `/app/main/profile/experience?userId=<id>`, click "+ Add", snapshot to get the
form's current refs, then fill:

| Field | Source |
|---|---|
| Company | extracted |
| Title | extracted |
| Summary | extracted or rewritten (Phase 5) — this is a rich-text editor; `fill` does not work on it — `click` into the editable region first, then `type` |
| Discriminator | `references/parsing.md`'s Discriminator heuristic |
| Industries | leave blank unless the CV clearly states one matching the fixed dropdown options |
| Skills | extracted, optional |
| Start Date / End Date | extracted — **not a free-text field**, see Date Fields below |

Click "Save". Snapshot and confirm the entry now appears in the Experience list before moving
to the next one — if it's not visible, check for a collapsed "N more" link at the end of the
list and click it before concluding the save failed.

### Education

Navigate to `/app/main/profile/education?userId=<id>`, click "+ Add Education", fill:

| Field | Source |
|---|---|
| School/Institution | extracted |
| Degree | extracted |
| Start Date / End Date | extracted — **not a free-text field**, see Date Fields below |

Click "Save". Snapshot and confirm the entry appears under "Education" before continuing.

### Certification & Exam

On the same `/app/main/profile/education?userId=<id>` page, click "+ Add" under
"Certification & Exam", fill:

| Field | Source | Notes |
|---|---|---|
| Certification Name | extracted | required |
| Certification Organization | extracted | required |
| Exam Date | extracted | required — already confirmed present in Phase 6; not a free-text field, see Date Fields below |
| Expiration Date / No Expiration | extracted | **one of the two is required** — the form blocks Save with an "Expiration date or No Expiration required" dialog if both are left empty. Default to checking "No Expiration" when the CV doesn't state an expiration date; never guess a date. |
| Certification Type | `references/parsing.md`'s Certification Type heuristic — use `select` on the combobox (option text, e.g. "Professional") | required |
| Certification Number | extracted | optional |
| Verification URL | extracted | optional |

Click "Save". Snapshot and confirm the entry appears under "Certification & Exam" before
continuing.

### Date Fields (Start Date, End Date, Exam Date, Expiration Date)

None of these are free-text inputs — `fill` produces "Invalid date" or a silently wrong value.
Clicking the field opens a calendar popup instead:

1. **Click the date field.** A `dialog "calendar"` appears, defaulting to the current month
   (Experience dates) or current day (Education/Certification dates).
2. **Click the year (or "Mon YYYY"/header) button** at the top of the calendar to jump straight
   to a year-range grid (e.g. "2019 - 2034") — this is far faster and more reliable than
   repeatedly clicking the "‹" previous-year arrow, which is easy to mis-time (clicks can
   silently no-op if fired before the previous render settles).
3. Click "‹"/"›" on the year-range grid if the target year isn't in the visible range, then
   click the year, then click the month.
4. **Experience Start/End Date stops here** — selecting the month closes the picker and fills
   the field as `Mon/YYYY` (e.g. `Aug/2021`).
5. **Education and Certification dates go one level deeper**: after clicking the month, a
   day-level grid appears (header shows e.g. "August 2012"). Click a day to fill the field as
   `MM/DD/YYYY`. When the CV only gives a month/year (no specific day), use day `1`.
   - **Watch for a leftmost week-number column** — in a day grid, the first cell of each row is
     an ISO week number, not a day, and it can display the same digit as a real day cell early
     in January (week "1" vs. day "1"). Identify the correct day cell by its column position
     under the weekday header (`Sun`/`Mon`/.../`Sat`), never by matching the first cell with
     the right text.
   - **Re-snapshot before clicking a day cell**, even if you just read its ref from the same
     snapshot that showed the month grid — clicking the month button re-renders the day grid
     and existing day-cell refs are consistently stale, causing an "element was detached from
     the DOM, retrying" error. Re-snapshot once and retry the same click with the fresh ref;
     don't treat this as a real failure until a retry with a fresh ref also fails.
6. After filling, snapshot and confirm the field shows the expected value before moving on —
   don't assume the click landed.

## Phase 8: Final Summary

Close the browser:
```bash
npx @playwright/cli@latest -s=engage close
```

Report: how many entries were added per section (Experience / Education / Certification &
Exam), how many were skipped as duplicates, and whether the description rewrite (Phase 5) was
applied.

## Error Handling

- **Blank snapshot right after navigation**: SPA render delay — snapshot again.
- **Click intercepted by an overlay**: prefer `goto` with the direct URL over sidebar clicks.
- **Required field missing from the CV** (e.g. a certification's Exam Date): flag it in the
  Phase 6 preview and block that entry — never guess a value.
- **DOCX text extraction fails or looks garbled**: tell the user and ask for a PDF instead of
  attempting a best-effort partial parse.
- **Session expired**: re-open the login URL, re-authenticate, resume from Phase 2.
- **Save fails, or the entry doesn't appear in the list after Save**: report which specific
  entry failed rather than silently moving on to the next one; also check for a collapsed
  "N more" link before concluding a save failed.
- **"Expiration date or No Expiration required" dialog blocks Save**: a Certification entry
  needs either an Expiration Date or the "No Expiration" checkbox — click "Ok" to dismiss the
  dialog, check "No Expiration" (unless the CV states an actual expiration date), then Save
  again.
- **"element was detached from the DOM, retrying" on a date-picker click**: the ref went stale
  because a parent calendar view (month/year) re-rendered — re-snapshot and retry the same
  click once with the fresh ref before treating it as a real failure. See Phase 7's Date
  Fields section.
