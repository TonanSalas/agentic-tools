# Engage CV Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/engage-cv-import` skill that parses a CV (PDF or DOCX), compares it
against what's already saved in the user's Improving Engage profile, and — only after the
user confirms — fills in the Experience, Education, and Certification & Exam sections via
Playwright CLI browser automation.

**Architecture:** One new skill directory, `.claude/skills/engage-cv-import/`, containing a
small stdlib-only Python script for DOCX text extraction (`scripts/extract_docx_text.py`),
two reference markdown files with classification/rewrite rules
(`references/parsing.md`, `references/resume-best-practices.md`), and a `SKILL.md` that
orchestrates the full flow: login → read current profile → extract CV data → deduplicate →
optionally rewrite descriptions → preview/confirm → fill forms → summarize. Follows the same
Playwright-CLI-via-Bash pattern as the existing `eip-points` skill (session `-s=engage`, no
MCP browser tools).

**Tech Stack:** Python 3 standard library only (`zipfile`, `xml.etree.ElementTree`,
`argparse`) for DOCX extraction — no `python-docx` or other pip dependency, matching this
repo's zero-dependency convention (see `team-activity`'s plan). Playwright CLI
(`npx @playwright/cli@latest`) via Bash for browser automation. Claude's `Read` tool for PDF
text extraction.

## Global Constraints

- No automated test framework exists in this repo (skills-only, no CI, no build system, per
  `CLAUDE.md`) — verification throughout this plan is manual: run the script/skill, inspect
  output, spot-check against the live Engage UI.
- **Never fabricate data.** A required field absent from the CV (e.g. a certification's Exam
  Date) must be flagged for the user, never guessed or defaulted. A rewritten Experience
  description must never contain a number, scope, or outcome that wasn't already present in
  the source CV text for that entry.
- **Never translate.** The source CV is in English; extracted text and any rewritten
  descriptions stay in English.
- **Never re-add or overwrite an entry already in the profile.** Deduplication (Phase 4) runs
  before anything is proposed to the user, and only entries confirmed as "New" in the Phase 6
  preview are ever filled in Phase 7.
- **Never hardcode `userId`.** It must be read at runtime from the logged-in user's own
  "Profile" nav link (its `?userId=` query param) — it's session/account-specific.
- Out of scope for this skill (do not implement): the "Talks" section, chaining into
  `eip-points` to register EIP points for new certifications, and Engage's native
  "Import from Resume / LinkedIn" feature (`/app/main/profile/resume-import`).
- Browser automation always uses Playwright CLI via Bash with session `-s=engage`,
  `--persistent --headed` on the initial `open` — no MCP browser tools (matches `eip-points`).
- Live Playwright element refs (`ref=...`) are per-session and regenerate on every snapshot —
  never hardcode a `ref=` value from this plan or the design spec; always re-snapshot.

---

### Task 1: `extract_docx_text.py` — stdlib-only DOCX text extraction

**Files:**
- Create: `.claude/skills/engage-cv-import/scripts/extract_docx_text.py`

**Interfaces:**
- Produces (consumed by Task 4's `SKILL.md`, Phase 3): a CLI invoked as
  `python3 extract_docx_text.py <path-to-docx> [--out <path>]`. Prints the extracted plain
  text to stdout (one line per paragraph, table rows rendered as `cell | cell | cell`), or
  writes it to `--out` if given. Exits with code `1` and a stderr message if the file doesn't
  exist or isn't a valid `.docx` (a corrupt/non-zip file).

- [ ] **Step 1: Write the core extraction function**

Create `.claude/skills/engage-cv-import/scripts/extract_docx_text.py`:

```python
#!/usr/bin/env python3
"""
Extract plain text from a .docx CV so it can be read the same way a PDF's
rendered text is (Claude's Read tool reads PDFs directly, but not .docx).

A .docx is a zip archive containing word/document.xml, which holds the
document body as WordprocessingML. This walks that XML directly with the
standard library instead of adding a python-docx dependency, matching this
repo's zero-external-dependency convention for scripts.
"""

import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_text(docx_path):
    """Return the docx's visible text: one line per paragraph, table rows as 'cell | cell'."""
    with zipfile.ZipFile(docx_path) as archive:
        xml_bytes = archive.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    body = root.find(f"{WORD_NS}body")

    lines = []
    for element in body:
        tag = element.tag
        if tag == f"{WORD_NS}p":
            text = "".join(node.text or "" for node in element.iter(f"{WORD_NS}t")).strip()
            if text:
                lines.append(text)
        elif tag == f"{WORD_NS}tbl":
            for row in element.iter(f"{WORD_NS}tr"):
                cells = []
                for cell in row.iter(f"{WORD_NS}tc"):
                    cell_text = "".join(
                        node.text or "" for node in cell.iter(f"{WORD_NS}t")
                    ).strip()
                    if cell_text:
                        cells.append(cell_text)
                if cells:
                    lines.append(" | ".join(cells))

    return "\n".join(lines)


if __name__ == "__main__":
    print(extract_text(sys.argv[1])[:2000])
```

The `if __name__ == "__main__"` block is a temporary manual-check hook, replaced by the real
CLI in Step 3.

- [ ] **Step 2: Generate a sample .docx and verify extraction against it**

macOS ships `textutil`, which can build a `.docx` from plain text — use it to create a
throwaway fixture (do not commit this file):

```bash
cat > /tmp/sample_cv.txt <<'EOF'
Jordan Rivera
Software Engineer

EXPERIENCE

Backend Engineer, Acme Corp
Jan 2022 - Present
Built and maintained REST APIs serving 10,000+ daily requests.
Reduced average response latency by 35% through Redis caching.

EDUCATION

B.S. Computer Science, State University
2018 - 2022

CERTIFICATIONS

AWS Certified Solutions Architect - Associate
Amazon Web Services, Issued March 2024
EOF

textutil -convert docx -output /tmp/sample_cv.docx /tmp/sample_cv.txt

python3 .claude/skills/engage-cv-import/scripts/extract_docx_text.py /tmp/sample_cv.docx
```

Expected: the printed text includes recognizable lines for `Jordan Rivera`,
`Backend Engineer, Acme Corp`, the `Reduced average response latency by 35%` bullet,
`B.S. Computer Science, State University`, and
`AWS Certified Solutions Architect - Associate` — confirming paragraph text survives the
round trip through a real `.docx` file, in the original order.

- [ ] **Step 3: Add the CLI wrapper (`--out`, error handling)**

Replace the temporary `if __name__ == "__main__"` block with:

```python
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Extract plain text from a .docx CV")
    parser.add_argument("docx_path", help="Path to the .docx file")
    parser.add_argument("--out", help="Write extracted text to this path instead of stdout")
    args = parser.parse_args()

    path = Path(args.docx_path)
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        text = extract_text(path)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        print(f"Error: could not read '{path}' as a .docx file ({e})", file=sys.stderr)
        sys.exit(1)

    if args.out:
        Path(args.out).write_text(text)
        print(f"Wrote {len(text)} chars to {args.out}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify the full CLI, including the error path**

```bash
python3 .claude/skills/engage-cv-import/scripts/extract_docx_text.py /tmp/sample_cv.docx
```

Expected: full extracted text printed to stdout (same content as Step 2, no longer truncated
at 2000 chars).

```bash
python3 .claude/skills/engage-cv-import/scripts/extract_docx_text.py /tmp/sample_cv.docx --out /tmp/sample_cv.txt.out
cat /tmp/sample_cv.txt.out
```

Expected: `Wrote <N> chars to /tmp/sample_cv.txt.out` on stderr, and the file contains the
same text.

```bash
python3 .claude/skills/engage-cv-import/scripts/extract_docx_text.py /tmp/does-not-exist.docx
echo "exit code: $?"
```

Expected: `Error: file not found: /tmp/does-not-exist.docx` on stderr, `exit code: 1`.

```bash
echo "not a docx" > /tmp/fake.docx
python3 .claude/skills/engage-cv-import/scripts/extract_docx_text.py /tmp/fake.docx
echo "exit code: $?"
```

Expected: an `Error: could not read '/tmp/fake.docx' as a .docx file (...)` message on
stderr, `exit code: 1` (not an unhandled traceback).

Clean up the scratch files:
```bash
rm -f /tmp/sample_cv.txt /tmp/sample_cv.docx /tmp/sample_cv.txt.out /tmp/fake.docx
```

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/engage-cv-import/scripts/extract_docx_text.py
git commit -m "$(cat <<'EOF'
Add extract_docx_text.py for stdlib-only DOCX text extraction

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `references/parsing.md` — classification and dedup rules

**Files:**
- Create: `.claude/skills/engage-cv-import/references/parsing.md`

**Interfaces:**
- Produces (consumed by Task 4's `SKILL.md`, Phases 4 and 7): a reference file read by Claude
  during those phases — no code interface, just markdown content.

- [ ] **Step 1: Write `references/parsing.md`**

Create `.claude/skills/engage-cv-import/references/parsing.md`:

```markdown
# Classifying and deduplicating CV entries

## Discriminator (Experience form)

The Experience form's "Discriminator" field has three options: `Improving Project`,
`External Experience`, `Other`.

- Use **Improving Project** if the Company field matches an Improving entity name
  (`Improving`, `Dragonfly`, `Dragonfly IC`, or a close variant).
- Use **External Experience** for any other named company — this is the default for the
  overwhelming majority of entries on a typical CV.
- Use **Other** only if the entry doesn't read as a company role at all (e.g. freelance work
  with no named employer, or a role you can't otherwise classify) — this should be rare.

## Certification Type (Certification & Exam form)

The Certification form's "Certification Type" field has three options: `Internal`,
`Professional`, `Partner`.

- Use **Internal** for ImprovingU-issued certifications (the org name/issuer is Improving or
  ImprovingU itself).
- Use **Partner** when the organization is explicitly a vendor partner program — look for
  "Partner" in the certifying body's name (e.g. "AWS Partner Network", "Microsoft Partner").
- Default to **Professional** for everything else (e.g. "AWS Certified Solutions Architect",
  "PMP", "CCNA", "Scrum Master") — this is the default for the overwhelming majority of
  entries on a typical CV.

## Date format

Confirm the live format expected by each date input via snapshot before filling (the
Experience/Education/Certification date fields may not all match `eip-points`'s
`MM/DD/YYYY` Date field) — fill a known-good date first if unsure, snapshot to see how it
rendered, and correct the format if it didn't parse as expected.

## Deduplication matching rule

Before proposing any entry to the user, compare it against the entries already on the
profile (read in Phase 2) using this rule — an extracted entry is a match (**"Already
exists"**) if **both** of the following hold:

1. **Name match**: the primary identifying field, normalized (trim whitespace, lowercase),
   is equal to or a substring of the existing entry's, or vice versa:
   - Experience: `Company + Title`
   - Education: `School/Institution + Degree`
   - Certification & Exam: `Certification Name`
2. **Date overlap**: the extracted entry's date range overlaps the existing entry's date
   range, or either range is unspecified/open-ended (e.g. "Present" or a missing end date).

If only the name matches but the dates clearly don't overlap (e.g. two separate stints at the
same company years apart), treat it as **New**, not a duplicate — CVs commonly list repeat
engagements.
```

- [ ] **Step 2: Sanity-check the file**

```bash
cat .claude/skills/engage-cv-import/references/parsing.md
```

Expected: the file renders as clean markdown with three `##` sections
(Discriminator, Certification Type, Deduplication matching rule) plus the Date format note —
read through it once and confirm nothing contradicts the design spec at
`docs/superpowers/specs/2026-08-06-engage-cv-import-design.md`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/engage-cv-import/references/parsing.md
git commit -m "$(cat <<'EOF'
Add parsing.md reference: discriminator/cert-type heuristics and dedup rule

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `references/resume-best-practices.md` — rewrite rules

**Files:**
- Create: `.claude/skills/engage-cv-import/references/resume-best-practices.md`

**Interfaces:**
- Produces (consumed by Task 4's `SKILL.md`, Phase 5): a reference file read by Claude only
  when the user opts into rewriting Experience descriptions — markdown content, no code
  interface.

- [ ] **Step 1: Write `references/resume-best-practices.md`**

Create `.claude/skills/engage-cv-import/references/resume-best-practices.md`:

```markdown
# Rewriting Experience descriptions: rules

Condensed from a broader resume best-practices document, scoped down to what's actually
actionable here: rewriting a single Experience entry's Summary field. The source document's
formatting/ATS/layout advice (fonts, columns, one-page-vs-two) doesn't apply — this skill
fills structured Engage form fields, it doesn't produce a resume file.

## The one hard rule

**Never introduce a number, scope, or outcome that isn't already present somewhere in the
source CV text for that entry.** This is a rewrite of phrasing and structure, not a fact
generator. If the source has no metric for a bullet, the rewritten version still has none —
strengthen the verb and clarity instead, don't invent a percentage to fill the gap.

## PAR formula

Structure each rewritten bullet as: **action verb + what was built/done + specific tools or
technologies + quantified result (only if that result is already in the source)**.

Example: `"Optimized Redis caching to reduce API latency by 71%, improving response times for
10k+ daily requests."` — every clause maps to something the source CV already said; the
rewrite's job was structure and verb strength, not new content.

## Action verbs to prefer

Built, Designed, Engineered, Programmed, Optimized, Streamlined, Standardized, Upgraded,
Solved, Led, Spearheaded, Improved, Reduced, Delivered, Implemented.

Avoid "responsible for", "worked on", "helped with", and passive voice generally — rewrite
those constructions into an active one using a verb from this list (or an equally strong verb
not on it) that's still true to what the source actually says.

## What's worth quantifying (only if the source already states it)

Performance (latency, throughput, uptime), scale (users, requests/sec, data volume),
reliability (incident/defect reduction), velocity (deployment frequency, release cadence),
cost (cloud spend, licensing).

## Language

The source CV is in English; rewritten bullets stay in English. Do not translate.
```

- [ ] **Step 2: Sanity-check the file**

```bash
cat .claude/skills/engage-cv-import/references/resume-best-practices.md
```

Expected: renders as clean markdown; the "one hard rule" section is present and unambiguous
(this is the section Phase 5 depends on most directly to avoid fabricating content) — read
through once and confirm it matches the "Resume optimization step" section of the design spec.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/engage-cv-import/references/resume-best-practices.md
git commit -m "$(cat <<'EOF'
Add resume-best-practices.md reference for the opt-in description rewrite

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `SKILL.md` — orchestration (login through final summary)

**Files:**
- Create: `.claude/skills/engage-cv-import/SKILL.md`

**Interfaces:**
- Consumes: `scripts/extract_docx_text.py` (Task 1, CLI as documented above),
  `references/parsing.md` (Task 2), `references/resume-best-practices.md` (Task 3).
- Produces: the `/engage-cv-import "<cv_path>"` slash command.

- [ ] **Step 1: Write `SKILL.md`**

Create `.claude/skills/engage-cv-import/SKILL.md`:

```markdown
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
| Summary | extracted or rewritten (Phase 5) — this is a rich-text editor; if `fill` doesn't work on it, `click` into the editable region first, then `type` |
| Discriminator | `references/parsing.md`'s Discriminator heuristic |
| Industries | leave blank unless the CV clearly states one matching the fixed dropdown options |
| Skills | extracted, optional |
| Start Date / End Date | extracted |

Click "Save". Snapshot and confirm the entry now appears in the Experience list before moving
to the next one.

### Education

Navigate to `/app/main/profile/education?userId=<id>`, click "+ Add Education", fill:

| Field | Source |
|---|---|
| School/Institution | extracted |
| Degree | extracted |
| Start Date / End Date | extracted |

Click "Save". Snapshot and confirm the entry appears under "Education" before continuing.

### Certification & Exam

On the same `/app/main/profile/education?userId=<id>` page, click "+ Add" under
"Certification & Exam", fill:

| Field | Source | Notes |
|---|---|---|
| Certification Name | extracted | required |
| Certification Organization | extracted | required |
| Exam Date | extracted | required — already confirmed present in Phase 6 |
| Expiration Date / No Expiration | extracted | check "No Expiration" if the CV implies it doesn't expire |
| Certification Type | `references/parsing.md`'s Certification Type heuristic | required |
| Certification Number | extracted | optional |
| Verification URL | extracted | optional |

Click "Save". Snapshot and confirm the entry appears under "Certification & Exam" before
continuing.

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
  entry failed rather than silently moving on to the next one.
```

- [ ] **Step 2: Manually verify the full skill end-to-end**

This requires the user's own real CV (never a third party's — see the design spec's
Non-goals). Ask the user for the path to their own CV (PDF or DOCX) if you don't already have
one, then invoke:

```
/engage-cv-import "<path-to-users-own-cv>"
```

Expected: the skill logs in, shows the Phase 6 combined preview table, asks about the
description rewrite (Phase 5) before that preview if there's an Experience entry with a
Summary, waits for confirmation, then — only after the user approves — fills the confirmed
entries. Confirm in the live Engage UI (`/app/main/profile/experience` and
`/app/main/profile/education`) that the new entries appear correctly with the right field
values.

- [ ] **Step 3: Verify deduplication on a second run**

Run the same command again:

```
/engage-cv-import "<path-to-users-own-cv>"
```

Expected: the Phase 6 preview now shows every previously-added entry tagged
"Ya existe — se omite", and confirming adds nothing new (or only genuinely new entries if the
CV was updated in between runs).

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/engage-cv-import/SKILL.md
git commit -m "$(cat <<'EOF'
Add engage-cv-import SKILL.md orchestrating login through final summary

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
