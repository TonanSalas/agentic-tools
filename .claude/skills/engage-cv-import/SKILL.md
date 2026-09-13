---
name: engage-cv-import
description: Parses a CV (PDF or DOCX) and populates the Improving Engage profile's Experience, Education, Certification & Exam, and Skills sections via Playwright CLI browser automation, skipping anything already saved and asking before adding anything new. Use when the user asks to import their CV/resume into Engage, sync their CV to their Engage profile, or update their Engage profile from their resume.
user-invocable: true
allowed-tools: Bash, Read
arguments:
  - name: cv_path
    description: "Absolute path to the CV file to import, PDF or DOCX."
    required: true
---

# Engage CV Import

You take a CV file, extract Experience/Education/Certification & Exam/Skills entries from
it, compare them against what's already saved on the user's Improving Engage profile
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

```bash
npx @playwright/cli@latest -s=engage goto "https://engage.improving.com/app/main/profile/skills-strengths?userId=<id>"
```

Snapshot. The saved skills live inside the **Top Skills** panel, which renders as a table that
is often empty in the snapshot until the editor is open — click that panel's **" Edit"** link,
snapshot, and record each existing skill's Name and Proficiency from the table shown above the
"Add New Skill" form. Click **" Close"** on the same panel when done — this is a read; nothing
is saved here.

Ignore the **Strengths (StrengthsFinder)** section on this page — it is not a CV field and this
skill never writes to it.

This baseline is what Phase 4 deduplicates against.

## Phase 3: Extract Data From the CV

Skills come from two places — an explicit "Skills"/"Technologies"/"Tech Stack" section, and
technologies named inside Experience bullets. Collect both, then merge duplicates.

- **PDF**: read `cv_path` directly with the `Read` tool.
- **DOCX**: run
  ```bash
  python3 "<skill-directory>/scripts/extract_docx_text.py" "<cv_path>"
  ```
  then work from that printed text (or use `--out <tmp-path>` and `Read` the result).

From the text, derive four structured lists:

| Section | Fields to extract |
|---|---|
| Experience | Company, Title, Summary/description, Start Date, End Date |
| Education | School/Institution, Degree, Start Date, End Date |
| Certification & Exam | Certification Name, Organization, Exam Date, Expiration Date (if stated), Certification Number (if stated), Verification URL (if stated) |
| Skills | Skill name, plus the evidence needed to propose a proficiency: how many years/which date spans the skill appears across, and whether it is a headline skill (named in a Skills/Technologies section or a role title) or only mentioned once in a bullet |

## Phase 4: Deduplicate

See `references/parsing.md`'s "Deduplication matching rule". For each extracted entry,
compare against the Phase 2 baseline and mark it:

- **New** — no match, will be proposed for addition
- **Already exists** — matched an existing entry, will be skipped; never re-added or
  overwritten

### Skills: catalog resolution

Skills need a second step. Engage's skill field is a **closed catalog** — a skill that isn't in
it cannot be created, only mapped or dropped. So for each **New** skill, resolve it against the
catalog before it reaches the preview, using the live typeahead (the same combobox Phase 7
fills — see its "Skill combobox" notes for the exact click/type/read sequence):

- **Exact match** — a catalog option equals the CV skill (normalized). Use it.
- **Substitute** — no exact option, but a clearly related one exists (e.g. `FastAPI` → `Python`
  or `REST API`). Propose it, marked as a substitution, and let Phase 6 decide — never silently
  swap one in.
- **No match** — the option list shows `No results found` and nothing related turns up. Drop the
  skill and report it in Phase 8; never invent a catalog entry.

Two extra rules: try a shortened stem before giving up (`Kubernet` finds `Kubernetes` plus the
managed-service variants that a full-string search can miss), and when the catalog returns
**several identical option labels** — `Python` appears twice — pick the first and note it in the
preview; they are duplicate catalog rows, not different skills.

Also propose, from the Phase 3 evidence, each new skill's **Proficiency**, **Is passion** and
**Is aspiration** values. These are proposals only — Phase 6 shows every one of them and the
user approves or corrects them before anything is filled. See `references/parsing.md`'s
"Proficiency, passion and aspiration proposals".

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
| Status | Name | Organization | Exam Date | Expiration | Type |
|--------|------|---------------|-----------|------------|------|
| Nuevo | AWS Certified Solutions Architect | Amazon Web Services | 03/2024 | ⚠ not stated in CV | Professional |
| Falta un dato | Scrum Master | Scrum Alliance | ⚠ no exam date in CV | — | — |

### Skills
| Status | CV skill | Engage catalog skill | Proficiency | Passion | Aspiration |
|--------|----------|----------------------|-------------|---------|------------|
| Nuevo | Python | Python | Craftsman | ✓ | — |
| Nuevo — sustitución | FastAPI | Python (FastAPI no está en el catálogo) | Peer | — | — |
| Ya existe — se omite | Kubernetes | Kubernetes | — | — | — |
| Sin match — se omite | Logfire | ⚠ no existe en el catálogo | — | — | — |
```

Proficiency, Passion and Aspiration are **proposals inferred from the CV**, not facts it states
— say so when presenting the table, and treat every value in those three columns as open for
the user to change. Nothing gets saved at a value the user hasn't seen.

For any entry tagged "Falta un dato", ask the user to supply the missing value or say to drop
that entry — never guess it. Ask:

**"¿Confirmas que agregue las entradas marcadas 'Nuevo'? Revisa sobre todo las columnas de
Proficiency, Passion y Aspiration de Skills — esas las inferí yo, no vienen del CV. Dime si algo
debe cambiar, o 'aprobado' para continuar."**

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
| Skills | extracted, optional — same closed catalog as the Skills section; fill it with the same click/type/portal-listbox sequence described under Skills below |
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
| Expiration Date / No Expiration | extracted | **one of the two is required** — the form blocks Save with an "Expiration date or No Expiration required" dialog if both are left empty. When the CV doesn't state an expiration date, flag it in the Phase 6 preview like a missing Exam Date and ask the user whether to mark the certification as non-expiring or supply a date — never check "No Expiration" without the user seeing that choice first. Only fill this field per the user's Phase 6 answer. |
| Certification Type | `references/parsing.md`'s Certification Type heuristic — use `select` on the combobox (option text, e.g. "Professional") | required |
| Certification Number | extracted | optional |
| Verification URL | extracted | optional |

Click "Save". Snapshot and confirm the entry appears under "Certification & Exam" before
continuing.

### Skills

Navigate to `/app/main/profile/skills-strengths?userId=<id>` and click the **" Edit"** link on
the **Top Skills** panel. The editor stays open across saves — **open it once and add every
approved skill inside that one editor**, rather than reopening it per skill.

> **Scope every ref to the "Add New Skill" section.** The saved-skills table sits directly
> above the form and contains *identical* star and checkbox elements. Taking the first match
> from a whole-page snapshot clicks a star **in an already-saved row**, silently re-rating a
> skill you added minutes ago, while the form stays untouched and "+ Add" stays disabled. Slice
> the snapshot from `Add New Skill` onward (`sed -n '/Add New Skill/,$p'`) before grepping for
> any ref. This is the single easiest way to corrupt existing data in this skill.

Per skill, in this order:

1. **Click the combobox to open the dropdown.** Match it as `combobox "<any name>"`, not
   `combobox "Select a skill"` — after the first add it keeps the *previously selected skill* as
   its accessible name.
2. **Fill the portal searchbox**, don't type into the combobox. Opening the dropdown creates a
   `searchbox [active]` in a portal at the very end of the snapshot, still holding the previous
   query. `fill <searchbox-ref> "<skill>"` replaces it reliably; `press ControlOrMeta+a` followed
   by `type` can close the list instead of refiltering, leaving no options at all.
3. **Read the options from the end of the snapshot** — `searchbox` → `listbox "Option List"` →
   `option`. They never render inside the form, so a form-only snapshot makes a working dropdown
   look broken.
4. **Click the option** approved in Phase 6. If the list shows `No results found`, try a shorter
   stem; if that also fails the skill should already have been dropped in Phase 4 — never type a
   name and click "+ Add" hoping free text sticks, it cannot.
5. **Click the proficiency star** for the approved level. The six stars' accessible names are
   `Learner`, `Novice`, `Associate`, `Peer`, `Craftsman`, `Master`; the panel's legend tooltip
   labels the same six positions `Aware`, `Novice`, `Practitioner`, `Journeyman`, `Expert`,
   `Master`. Position N means the same level in both — click by the star's accessible name, and
   use the legend name when talking to the user. **The option click re-renders the form and
   staleness makes this click no-op silently**: after clicking, check whether "+ Add" is still
   `[disabled]`, and if it is, re-snapshot and click the star again (up to ~3 tries).
6. **Click "+ Add".** The button is `[disabled]` until *both* a catalog skill and a proficiency
   are set — a still-disabled button means step 4 or step 5 didn't land, not that the skill is
   invalid.
7. **Confirm the skill appears in the editor's table** before starting the next one.

**Passion and aspiration are set afterwards, on the saved row — not in the form.** Ticking the
form's "Is passion" / "Is aspiration" checkboxes does *not* carry into the created skill; the
row comes back with both off. After a skill is added, toggle them on its table row instead: each
row carries a fire icon (passion) and a hammer icon (aspiration), rendered as an enabled/disabled
pair where only one of each pair is visible. Click the *visible* one to turn the flag on:

```bash
npx @playwright/cli@latest -s=engage eval "() => { const r=[...document.querySelectorAll('table tbody tr')].find(x=>x.cells[0]?.innerText.trim()==='<skill>'); const i=[...r.cells[1].querySelectorAll('i')].filter(e=>/passion/.test(e.className) && getComputedStyle(e).display!=='none')[0]; i.click(); }"
```

The saved rows' stars are clickable the same way, which is also how to repair a rating that got
clicked by mistake — `stars[N-1].click()` on that row sets it to level N.

To change a level or flag on a skill that's already saved, leave it alone — this skill only
adds; existing entries are never overwritten.

Click **" Close"** on the panel when every approved skill is added, then **reload the page,
reopen the editor and verify against the server** rather than trusting the add loop's own
output. Snapshots are verbose for 20+ rows; read the whole table in one call instead:

```bash
npx @playwright/cli@latest -s=engage eval "() => { const t=[...document.querySelectorAll('table')].map(t=>[...t.querySelectorAll('tbody tr')]).sort((a,b)=>b.length-a.length)[0]||[]; return t.map(r=>{const n=r.cells[0].innerText.trim(); const d=[...r.querySelectorAll('li i')].filter(e=>e.className.includes('progtrckr-done')).length; const on=[...r.cells[1].querySelectorAll('i')].filter(i=>/passion|aspiration/.test(i.className) && !i.className.includes('skill-disabled') && getComputedStyle(i).display!=='none').map(i=>i.className.match(/passion|aspiration/)[0]); return n+' '+d+'/6 '+on.join(',');}); }"
```

Note the read-only page (editor closed) shows only a *Top Skills* subset plus category rollups —
the full list lives in the editor, so verify with the editor open.

### Date Fields (Start Date, End Date, Exam Date, Expiration Date)

None of these are free-text inputs — `fill` produces "Invalid date" or a silently wrong value.
Clicking the field opens a calendar popup instead:

0. **If the CV's End Date is "Present" (or otherwise indicates the role/credential is
   ongoing)**, leave the End Date field empty — do not open its calendar picker at all. There
   is no date to pick; clicking through the picker anyway risks selecting a real date and
   incorrectly ending an ongoing entry.
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

Report: how many entries were added per section (Experience / Education / Certification & Exam
/ Skills), how many were skipped as duplicates, and whether the description rewrite (Phase 5)
was applied. For Skills, report the count verified **after a page reload**, not the add loop's
own tally, and list separately how many went in as **substitutions** and, by
name, which CV skills were dropped as **not in the Engage catalog** — those are the ones the
user may want to raise with whoever maintains the catalog.

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
  dialog, then fill whichever the user chose in Phase 6 (an Expiration Date, or "No
  Expiration" if the user confirmed the credential doesn't expire), then Save again. This
  dialog should only ever be hit for a value the user already picked in Phase 6 — never decide
  which one to check here.
- **Skill dropdown looks empty after typing**: the options render in a portal at the *end* of
  the snapshot (`searchbox` → `listbox "Option List"`), not inside the form — read the tail of
  the snapshot before concluding the typeahead failed.
- **`No results found` in the skill dropdown**: the catalog has no such skill. Retry with a
  shorter stem once, then treat it as a "Sin match" entry — report it in Phase 8 and move on.
  Free text cannot be saved; "+ Add" stays disabled.
- **"+ Add" stays disabled**: either no catalog option is selected (re-open the dropdown and
  click a real option) or — more often — the proficiency star click went to a stale ref, or to
  the saved-rows table instead of the form. Re-snapshot, re-slice from `Add New Skill`, and click
  the star again.
- **A previously added skill's rating changed on its own**: a star ref was taken from a
  whole-page snapshot and landed in the saved-rows table. Check the whole table's ratings with
  the verification `eval` above, and repair the row by clicking its correct star.
- **Dropdown shows no options at all after "typing"**: the query went somewhere other than the
  portal searchbox. Re-open the dropdown and use `fill <searchbox-ref>` instead of `type`.
- **"element was detached from the DOM, retrying" on a date-picker click**: the ref went stale
  because a parent calendar view (month/year) re-rendered — re-snapshot and retry the same
  click once with the fresh ref before treating it as a real failure. See Phase 7's Date
  Fields section.
