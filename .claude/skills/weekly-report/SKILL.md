---
name: weekly-report
description: Generate a weekly status report with "What I did this week" and "Goals for next week", grouped by project in a bulleted hierarchy. Pulls GitHub activity via the weekly-activity skill, reorganizes it by project/task, and optionally sends it to Teams via teams-messenger. Use when the user asks for a weekly report, status update, standup summary, weekly recap, or wants to share what they worked on.
user-invocable: true
allowed-tools: Bash, Skill, Read, Write, Edit
arguments:
  - name: week
    description: "Which week to report on: 'this' (default) or a date range like '2026-04-07..2026-04-11'"
    required: false
  - name: teams-target
    description: "Teams chat or channel to send the report to. Defaults to 'Dragonfly Team' if not specified."
    required: false
  - name: next-week-goals
    description: "Manual goals for next week that supplement auto-detected WIP items. Can be free-form text."
    required: false
---

# Weekly Report

You generate a weekly status report for Tonan Salas. The report has two sections — what was accomplished this week and goals for next week — organized as a bulleted hierarchy grouped by project.

## Report Format

The report uses dashes (`-`) with indentation to create a hierarchy. Each deeper level adds 4 spaces of indentation. Here is the exact format:

```
*What I did this week*
- <Project>
    - <Task or sub-group>
        - <Sub-task or detail>
            - <Deeper detail>
- <Project>
    - <Task>

*Goals for next week*
- <Project>
    - <Sub-group>
        - <Goal>
            - <Detail or note>
    - <Goal>
```

The hierarchy has up to 4 levels:
- **Level 1** (no indent): Project name (e.g., Broker Assist, Agentic Org)
- **Level 2** (4 spaces): Major task, feature area, or sub-group
- **Level 3** (8 spaces): Specific task, issue, or detail within that area
- **Level 4** (12 spaces): Individual items within a group (e.g., carrier names, sub-notes)

The section headers (*What I did this week* and *Goals for next week*) are in italics and stand alone above the list.

## Phase 1: Gather Activity (with ticket state)

Call `gather_activity.py` directly with `--json` so each ticket comes back with its state already attached — no per-ticket `gh` calls needed downstream. This also hits the shared cache, so a same-week chain from `workday-timelogger` won't re-fetch.

```bash
python3 .claude/skills/weekly-activity/scripts/gather_activity.py \
  --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> --json
```

If `week` was provided, use that range. If not (or `week == "this"`), default to `$(date -v-Mon +%Y-%m-%d)` through `$(date +%Y-%m-%d)`.

The JSON has `tickets[]` with one entry per unique ticket. Each entry includes:
- `repo`, `number`, `title`
- `state` — `"open"`, `"closed"`, or `"unknown"`
- `state_reason` — e.g. `"completed"`, `"not_planned"`, `"reopened"`, or `null`
- `is_pr` — true if it's a PR (not an issue)
- `merged` — true/false for PRs, `null` for issues
- `days`, `sources`

## Phase 2: Classify Each Ticket

Use the JSON state fields directly — no extra `gh` calls. Classify each ticket:

- **Done**: `is_pr && merged`, OR (`!is_pr && state == "closed" && state_reason == "completed"`)
- **Skip**: `state_reason == "not_planned"` (won't-fix, don't surface anywhere)
- **In progress**: everything else (open issues, open PRs, reopened issues)

Only **Done** items go in "What I did this week." **In progress** items go in "Goals for next week." A ticket can appear in both sections if meaningful — e.g. an issue that's partially closed via merged PR but reopened for remaining work.

## Phase 3: Organize by Project

Transform the classified tickets into a project-grouped hierarchy:

1. **Deduplicate**: Collect all unique tickets across all days. A ticket that appeared on Monday and Wednesday shows up only once.

2. **Group by project**: The repo name is the primary project grouping. Map repo short names to friendly project names:

   | Repo pattern          | Project name     |
   |-----------------------|------------------|
   | `broker-assist*`      | Broker Assist    |
   | `agentic-org*`        | Agentic Org      |
   | `agentic-tools`       | Skills           |
   | `improving-agentic-*` | Skills           |
   | Other repos           | Use repo name, title-cased |

3. **Cluster and summarize related items**: Within each project, look for natural groupings (e.g., multiple carrier tickets, multiple COI tickets, email sync tickets). When 2+ tickets are clearly part of the same effort, **collapse them into a single summary line** with key details in parentheses. This keeps the report concise without losing important context.

   Examples of collapsing:
   - 3 tickets about adding 1Fort carrier → `Add 1Fort carrier (config, documentation, 2FA setup)`
   - 2 tickets about email sync batching and config → `Improve email sync (batch IMAP fetch, configurable lookback window)`
   - 2 security tickets → `Harden API surface against scraping/probing attack`

   Only keep items as separate lines when they represent genuinely distinct work streams. The goal is one line per logical accomplishment, not one line per ticket.

   Single items that don't cluster with anything stay at level 2 directly under the project, as-is.

4. **Write human-readable descriptions**: Don't just paste raw issue titles. Rephrase them into concise, natural descriptions. Drop conventional commit prefixes (feat:, fix:, chore:). No ticket numbers in the final output.

5. **Drop unknowns**: Skip any ticket with an `(unknown #N)` title.

## Phase 4: Build "Goals for Next Week"

The goals section combines **in-progress tickets** (from Phase 2) with user-provided goals:

**Auto-detected goals**: All tickets classified as "In progress" in Phase 2 — open PRs, open issues, and any work that was started but not finished this week. These are the primary source of next-week goals.

**User-provided goals**: If the user passed `next-week-goals`, incorporate them into the hierarchy alongside the auto-detected items. If not, present the auto-detected goals and ask: "Here are potential next-week goals based on open work. Want to add, remove, or change anything?"

Goals can include subjective notes and planning items (not just ticket titles). For example, "We are missing some tests/evals" or "Maybe making COI a subagent" are valid goal entries. Nest these as sub-details under the relevant goal.

Group next-week goals by project using the same hierarchy.

## Phase 5: Format and Present the Bulleted Report (Output 1 — Google Docs)

Produce the bulleted hierarchy report. Key rules:
- Use `-` (dash) for every bullet at every level
- Indent 4 spaces per level
- Section headers in italics: `*What I did this week*` and `*Goals for next week*`
- No ticket numbers — human-readable descriptions only
- One blank line between the two sections

Show this report to the user and ask: "Does this look right? Want to change anything before I generate the TEC status report?"

This output is for the user to paste into Google Docs manually — do NOT send it to Teams.

## Phase 6: Generate TEC Weekly Status Report (Output 2 — Teams)

Once the user confirms the bulleted report (or has no changes), use the "What I did" and "Goals for next week" data to generate a **TEC Weekly Status Report**. This is a separate, professional-toned report formatted for Confluence/Teams.

Use this exact template:

```
# TEC Weekly Status Report – Dragonfly

**Project:** Dragonfly
**Date:** <today's date, e.g. April 11, 2026>
**Status:** 🟢 / 🟡 / 🔴

## Summary
<High-level summary, 2–4 sentences. Synthesize the main themes from what was accomplished. Mention key milestones, notable completions, or areas of focus. Professional and concise.>

## Accomplished
* <Item from "What I did this week", rephrased as a clear accomplishment>
* <Item>
* <Item>

## Planned Activities
* <Item from "Goals for next week", rephrased as a planned action>
* <Item>

## Risks
<List any risks if apparent from the data (e.g., blocked items, open security issues). Otherwise write: "No risks identified at the moment.">

## Shoutouts
<Include if the user mentioned any shoutouts. Otherwise omit this section entirely.>
```

Guidelines for generating the TEC report:
- **Status color**: Default to 🟢 (Green) unless there are clear blockers or risks. Use 🟡 if there's notable risk. Use 🔴 only if there are critical blockers.
- **Summary**: Write 2–4 sentences that give a high-level picture. Don't just list items — synthesize the themes (e.g., "Strong progress on COI workflow with carrier-first delivery and reliability improvements merged. Email sync enhancements deployed for both Agentic Org and Broker Assist.")
- **Accomplished**: Flatten the bulleted hierarchy into a simple bulleted list. Each item should be a clear, standalone accomplishment. Combine related sub-items into single lines where appropriate (same collapsing logic as the bulleted report).
- **Planned Activities**: Convert goals into action-oriented statements (e.g., "Continue COI workflow — address remaining unmet requirements").
- **Risks**: Derive from open issues, security incidents, or blockers visible in the data. If nothing stands out, say no risks.
- **Shoutouts**: Only include if the user explicitly mentioned shoutouts in their input. Don't fabricate them.

Show the TEC report to the user and ask: "Ready to send to Teams, or any changes?"

## Phase 7: Send TEC Report to Teams

Once the user confirms, send the **TEC report** (not the bulleted report) via Teams. The default target is "Dragonfly Team" unless the user specified a different one:
```
skill: "teams-messenger", args: "<the TEC report text>" "<teams-target or 'Dragonfly Team'>"
```

**Formatting for Teams**: Pass the TEC report as HTML so teams-messenger can paste it with rich formatting into Teams. Convert the report to this HTML structure:

```html
<b>TEC Weekly Status Report – Dragonfly</b><br>
<b>Project:</b> Dragonfly<br>
<b>Date:</b> April 11, 2026<br>
<b>Status:</b> 🟢<br>
<br>
<b>Summary</b><br>
Summary paragraph text here.<br>
<br>
<b>Accomplished</b>
<ul>
<li>Item one</li>
<li>Item two</li>
</ul>
<b>Planned Activities</b>
<ul>
<li>Goal one</li>
<li>Goal two</li>
</ul>
<b>Risks</b><br>
No risks identified at the moment.
```

Do NOT use markdown, `•` characters, or `*` bullets — pass actual HTML so Teams renders bold headers and native bullet lists.

## Error Handling

- **No activity found**: Tell the user — maybe they need a different date range.
- **Repo not in mapping table**: Use the repo name title-cased as the project name. Mention it so the user can provide the correct mapping.
- **Teams send fails**: Show the report in the conversation so the user can copy-paste manually.
