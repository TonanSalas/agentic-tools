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
