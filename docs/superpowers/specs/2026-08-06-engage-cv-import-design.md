# Engage CV Import — Design

## Purpose

A new skill, `/engage-cv-import`, that takes a CV file (PDF or DOCX) and populates the
Improving Engage profile (`https://engage.improving.com`) with the candidate's work
Experience, Education, and Certification & Exam entries — without duplicating anything
already saved there, and without inventing facts the CV doesn't contain.

Unlike `eip-points` (which registers involvement activities), this skill edits the
**Profile** section of Engage: `/app/main/profile/experience`, `/app/main/profile/education`
(which holds both "Education" and "Certification & Exam" subsections). The CV is parsed by
Claude directly (not Engage's native `resume-import` importer — see Non-goals), giving full
control over field mapping, deduplication, and optional rewrite of experience descriptions.

Usage: `/engage-cv-import "/path/to/cv.pdf"`

## Non-goals

- **Does not use Engage's native "Import from Resume / LinkedIn" feature**
  (`/app/main/profile/resume-import`). That importer's post-upload review screen was not
  inspected (avoided uploading a third party's CV to a live account during design), and using
  it would forfeit control over deduplication and the optional rewrite step. Parsing is done
  by Claude instead.
- **Does not fill the "Talks" section.** Talks is a multi-step wizard (Basics → Abstract →
  Sessions → Review) with audience-size/duration/type pickers unrelated to CV content
  structure — out of scope for this first version.
- **Does not chain into `eip-points`.** A new certification could also justify logging EIP
  points (`Certification/Recognition` category), but this skill only updates the Profile;
  registering points stays a separate, manually-triggered action.
- **Does not translate.** The source CV is in English; extracted text and any rewritten
  descriptions stay in English.
- **Does not touch Skills & Strengths or Growth sections** — only Experience, Education, and
  Certification & Exam.

## Architecture

```
.claude/skills/engage-cv-import/
  SKILL.md
  references/
    parsing.md                 # classification-style rules: discriminator/cert-type
                                # heuristics, date format, dedup matching rule
    resume-best-practices.md   # condensed from the user-supplied best-practices doc:
                                # PAR formula, action verb list, what to quantify,
                                # explicit no-fabrication rule
  scripts/
    extract_docx_text.py       # python-docx based .docx -> plain text, for CVs in
                                # Word format (PDFs are read directly via the Read tool)
```

All browser automation uses Playwright CLI via Bash with session `-s=engage`, matching
`eip-points`. `snapshot` to read the page, `click`/`fill`/`select` with refs from the
snapshot — no MCP browser tools.

## Phases

### Phase 1 — Launch Browser & Login

Same as `eip-points`: open `https://engage.improving.com/account/login`
(`--persistent --headed`), click "Login with Improving", wait for interactive SSO if needed.
Confirm landing on `/app/main/dashboard/employee-home`.

### Phase 2 — Read Current Profile

Navigate to `/app/main/profile/experience?userId=<id>` and
`/app/main/profile/education?userId=<id>` (get `<id>` from the "Profile" nav link's
`userId` query param, discovered at login time — never hardcode it). Snapshot each and
extract the existing entries:

- Experience: Company, Title, Start/End Date
- Education: School/Institution, Degree, Start/End Date
- Certification & Exam: Certification Name, Organization

This becomes the baseline for deduplication in Phase 4.

### Phase 3 — Extract Data From the CV

- **PDF**: read directly with the `Read` tool.
- **DOCX**: run `scripts/extract_docx_text.py <path>` to get plain text via `python-docx`,
  then read that output.

From the text, derive three structured lists:

| Section | Fields extracted |
|---|---|
| Experience | Company, Title, Summary/description, Start Date, End Date |
| Education | School/Institution, Degree, Start Date, End Date |
| Certification & Exam | Certification Name, Organization, Exam Date, Expiration Date (if stated), Certification Number (if stated), Verification URL (if stated) |

### Phase 4 — Deduplicate

Compare each extracted entry against the Phase 2 baseline using the matching rule in
`references/parsing.md` (normalized-name match + date-range overlap). Mark each extracted
entry as one of:

- **New** — no match found, will be proposed for addition
- **Already exists** — matched an existing entry, will be skipped (never re-added, never
  overwritten)

Entries later confirmed by the user in Phase 6 are the only ones acted on in Phase 7 — a
duplicate is never written even if the user doesn't explicitly review it.

### Phase 5 — Ask About Rewriting Descriptions

Only if at least one **New** Experience entry has a Summary/description: ask the user whether
to rewrite those descriptions following `references/resume-best-practices.md` (PAR formula —
Problem/Action/Result —, strong action verbs, results-first phrasing).

**Hard constraint**: the rewrite may restructure and strengthen wording, but must never
introduce a metric, scope number, or outcome that is not already present somewhere in the
source CV text for that entry. If a bullet has no number in the source, the rewritten version
still has none.

This step never touches Education or Certification entries — those are factual fields with
no narrative text to rewrite. Rewriting stays in English (matching the source CV; see
Non-goals).

If the user declines, the extracted text is used as-is.

### Phase 6 — Preview & Confirm

Present one combined table (three sections: Experience / Education / Certification & Exam),
covering every extracted entry:

- **New** entries: show the values that will be filled (post-rewrite text if Phase 5 was
  accepted), tagged `Nuevo`
- **Already exists** entries: tagged `Ya existe — se omite`, shown but not actionable
- **Missing required field** entries (e.g. a certification with no Exam Date in the CV, which
  Engage's form requires): tagged `Falta un dato`, blocking that specific entry until the user
  supplies the value or removes it from the batch

Ask for confirmation. If the user requests changes (edit a field, drop an entry), update and
re-present. Never invent a value for a flagged missing-required-field entry.

### Phase 7 — Fill Forms

For each confirmed **New** entry, in this field mapping (refs found live during design,
confirm current refs via snapshot at implementation/runtime — Engage's SPA re-renders refs
per session):

**Experience** (`/app/main/profile/experience`, "+ Add"):
| Field | Source | Notes |
|---|---|---|
| Company | CV | |
| Title | CV | |
| Summary | CV (or rewritten, per Phase 5) | rich-text editor |
| Discriminator | heuristic | "Improving Project" if company matches Improving entities, else "External Experience" — see `parsing.md` |
| Industries | — | left blank unless CV states one matching the fixed option list |
| Skills | CV | tag search, optional |
| Start Date / End Date | CV | |

**Education** (`/app/main/profile/education`, "+ Add Education"):
| Field | Source |
|---|---|
| School/Institution | CV |
| Degree | CV |
| Start Date / End Date | CV |

**Certification & Exam** (`/app/main/profile/education`, "+ Add" under Certification & Exam):
| Field | Source | Notes |
|---|---|---|
| Certification Name * | CV | required |
| Certification Organization * | CV | required |
| Exam Date * | CV | required — flagged in Phase 6 if absent, never guessed |
| Expiration Date / No Expiration | CV | check "No Expiration" if CV implies it doesn't expire |
| Certification Type * | heuristic | Internal / Professional / Partner — see `parsing.md` |
| Certification Number | CV | optional |
| Verification URL | CV | optional |

After each Save, snapshot to confirm the entry now appears in that section's list before
moving to the next entry.

### Phase 8 — Final Summary

Report, per section: how many entries were added, how many were skipped as duplicates, and
whether the description rewrite was applied.

## `references/parsing.md` contents

- **Discriminator heuristic**: "Improving Project" if the Company field matches an Improving
  entity name (e.g. "Improving", "Dragonfly"), else "External Experience"; "Other" only if
  neither applies and the entry doesn't read as a company role at all.
- **Certification Type heuristic**: "Internal" for ImprovingU-issued certs; "Partner" for
  vendor partner-program certs (e.g. "AWS Partner", "Microsoft Partner"); default
  "Professional" otherwise.
- **Date format**: confirm the live input's expected format via snapshot at implementation
  time (likely `MM/DD/YYYY`, consistent with `eip-points`'s Date field).
- **Dedup matching rule**: normalize whitespace/case on the primary name field (Company+Title
  for Experience, School+Degree for Education, Certification Name for Certifications), treat
  as a match if the normalized names are equal (or one contains the other) **and** date ranges
  overlap or are both unspecified.

## `references/resume-best-practices.md` contents

Condensed from the user-supplied best-practices document, scoped to what's actionable for
rewriting a single Experience Summary field (the formatting/ATS/layout guidance doesn't apply
— Engage isn't parsing an uploaded document, it's structured form fields):

- **PAR formula** (Problem/Action/Result): action verb + what was built/done + specific
  tools/technologies + quantified result, when a result is already present in the source.
- **Action verb list** (from Harvard/MIT): Built, Designed, Engineered, Programmed, Optimized,
  Streamlined, Standardized, Upgraded, Solved, Led, Spearheaded, Improved, Reduced, Delivered,
  Implemented — avoid "responsible for" and passive voice.
- **What to quantify when present in the source**: performance (latency, throughput, uptime),
  scale (users, requests/sec, data volume), reliability (incident/defect reduction), velocity
  (deployment frequency), cost.
- **Explicit rule, restated for this skill's context**: this is a rewrite aid, not a fact
  generator — never add a number, scope, or outcome absent from the source CV.

## Error Handling

- **Blank snapshot right after navigation**: SPA render delay — snapshot again (same as
  `eip-points`).
- **Click intercepted by `drawer-overlay`**: prefer `goto` with direct URLs over sidebar
  clicks.
- **Required field missing from CV** (e.g. Certification Exam Date): flag in the Phase 6
  preview, block that entry, never guess a value.
- **DOCX text extraction fails/garbled**: report the failure and ask the user to supply a PDF
  instead, rather than attempting a best-effort partial parse.
- **Session expired**: re-open the login URL, re-authenticate, resume from Phase 2.
- **Save fails / entry doesn't appear after Save**: report which specific entry failed rather
  than silently continuing to the next one.

## Testing

No automated test suite in this repo (skills-only). Verification is manual:

- Run the skill against a real CV (the user's own — never a third party's) and confirm new
  Experience/Education/Certification entries appear correctly in the live Profile.
- Run it a second time with the same CV and confirm nothing is duplicated (Phase 4 correctly
  marks everything "Already exists").
- Test the Phase 5 rewrite: confirm accepted rewrites read as PAR-formula bullets, and confirm
  no rewritten bullet contains a number absent from the source CV.
- Test a CV with a certification missing an Exam Date and confirm it's flagged in Phase 6
  rather than silently skipped or guessed.
- Test with a DOCX CV to confirm the `extract_docx_text.py` path works end to end.

## Open Questions / Risks

- **Live field refs and exact date-input format** were captured during design-phase browsing
  but Engage's SPA re-generates refs per session — implementation must re-snapshot rather than
  hardcode any `ref=` value from this document.
- **Engage's native resume-import review screen was never inspected** (see Non-goals) — if a
  future iteration wants to compare against it or fall back to it, that screen still needs a
  first look, ideally with the user's own CV.
- **Rich-text Summary field**: the Experience form's Summary is a rich-text editor (bold/
  italic/underline/lists) rather than a plain textbox — implementation needs to confirm how
  Playwright CLI's `fill` interacts with it (may need `click` + `type` into the editable region
  instead).
