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

## Proficiency, passion and aspiration proposals

Engage requires a proficiency level on every skill, and a CV essentially never states one. Infer
a proposal from what the CV *does* show, then let the user correct it in the Phase 6 preview —
these are proposals, never findings.

The six stars, in order, with the panel legend's label in parentheses:

| Star (accessible name) | Legend label | Propose when the CV suggests |
|---|---|---|
| Learner | Aware | Listed once in passing, or framed as something being learned |
| Novice | Novice | Used in a single short engagement, under ~1 year |
| Associate | Practitioner | Used across ~1-3 years, or in one substantial role |
| Peer | Journeyman | Used across ~3-6 years or several roles |
| Craftsman | Expert | A headline skill spanning most of the career, or one the CV ties to leading or architecting work |
| Master | Master | Only when the CV is explicit — training or mentoring others in it, a matching certification, or a stated expert level |

When the evidence is thin, propose the lower level. It is easier for the user to raise a value in
the preview than to notice an inflated one.

**Is passion** — propose checked only for a skill the CV itself signals enthusiasm for: it leads
the Skills section, recurs across most roles, or appears in a summary/objective statement.

**Is aspiration** — propose checked only for a skill framed as forward-looking: currently being
learned, a recent certification with little role history behind it, or named as a career
direction.

Default both to unchecked. Neither is something a CV usually states, and an unchecked box is the
honest answer when the CV doesn't say.

## Skill catalog matching

Engage's skill field is a closed catalog served by a typeahead — free text cannot be saved. When
resolving an extracted skill against it:

- Search on a **stem**, not the full string. `Kubernet` surfaces `Kubernetes`,
  `Azure Kubernetes Service (AKS)` and `Amazon Elastic Kubernetes Service (EKS) (AWS)`; a longer
  query can miss the variants.
- Prefer the **plain option** over a vendor-qualified one unless the CV is specific about the
  vendor (`Kubernetes`, not `Azure Kubernetes Service (AKS)`, unless the CV says AKS).
- The catalog contains **duplicate labels** — `Python` returns two identical options. Take the
  first and note it in the preview; they are duplicate catalog rows, not distinct skills.
- A tool absent from the catalog (e.g. `FastAPI`) may be proposed as a **substitution** to its
  nearest catalog concept (`Python`, `REST API`), marked as a substitution in the preview. If
  the substitution would lose the meaning, propose nothing and let the skill be dropped.

## Date format

Date fields are calendar pickers, not free-text inputs — see `SKILL.md`'s "Date Fields"
subsection under Phase 7 for the exact click sequence and per-section format
(`Mon/YYYY` for Experience, `MM/DD/YYYY` for Education/Certification).

## Deduplication matching rule

Before proposing any entry to the user, compare it against the entries already on the
profile (read in Phase 2) using this rule — an extracted entry is a match (**"Already
exists"**) if **both** of the following hold:

1. **Name match**: the primary identifying field, normalized (trim whitespace, lowercase),
   is equal to or a substring of the existing entry's, or vice versa:
   - Experience: `Company + Title`
   - Education: `School/Institution + Degree`
   - Certification & Exam: `Certification Name`
   - Skills: `Skill Name`
2. **Date overlap**: the extracted entry's date range overlaps the existing entry's date
   range, or either range is unspecified/open-ended (e.g. "Present" or a missing end date).

**Skills are name-only**: they carry no dates, so condition 2 is always satisfied and a
normalized name match alone makes a skill a duplicate. Normalize a bit harder for them — trim,
lowercase, and strip punctuation and spacing (`Node.js` / `NodeJS` / `node js` are one skill).

If only the name matches but the dates clearly don't overlap (e.g. two separate stints at the
same company years apart), treat it as **New**, not a duplicate — CVs commonly list repeat
engagements.
