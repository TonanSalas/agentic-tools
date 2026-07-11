# Team Activity Report — Design

## Purpose

A new skill, `/team-activity`, that reports on team-wide engineering activity across a date
range:

1. **PRs merged per day**, across all `dragonflyic` repos (not just the current user), with a
   per-repo breakdown.
2. **Linear communication volume**: comment count per ticket, and total comment count per day,
   across all teams in the Linear workspace.

This is distinct from the existing `weekly-activity` skill, which is scoped to a single GitHub
user's own activity. `team-activity` is a team-wide/org-wide view intended for spotting velocity
and communication trends, not for personal timesheet/report generation.

## Non-goals

- Not a scheduled/recurring report (on-demand skill invocation only, for now).
- Not a visual dashboard — output is a markdown report, consistent with other skills in this repo.
- Not scoped to a specific Linear team — covers the whole workspace.
- Does not replace or modify `weekly-activity`, `weekly-report`, or any personal-activity skill.

## Architecture

One new skill: `.claude/skills/team-activity/`

```
.claude/skills/team-activity/
  SKILL.md
  scripts/
    gather_pr_merges.py
  cache/                      # gitignored, created at runtime
```

- `gather_pr_merges.py` handles the GitHub side: a standalone, cacheable, deterministic script,
  following the same conventions as `weekly-activity/scripts/gather_activity.py`.
- The Linear side has **no script**. Linear MCP tools are only reachable from within a Claude
  Code session, not from a Bash-invoked Python process, so `SKILL.md` instructs Claude to call
  the connected Linear MCP tools directly at runtime and assemble the comment tallies itself.
- `SKILL.md` orchestrates both parts and renders one combined markdown report.

## Component: `gather_pr_merges.py` (GitHub, org-wide PR merges)

### Why not reuse `gather_activity.py`'s approach

`gather_activity.py` discovers repos via the Events API filtered to one actor
(`users/{GH_USERNAME}/events`), which only surfaces repos *that user* touched. `team-activity`
needs merged PRs from **any** author across **all** dragonflyic repos, so repo discovery via a
single user's event stream doesn't work.

### Approach

Use a single paginated GitHub search call across the whole org, instead of enumerating repos and
querying each one individually:

```
gh search prs --owner dragonflyic "merged:<start>..<end>" \
  --json repository,number,title,mergedAt,author,url --limit 1000
```

This returns every merged PR in the org for the date range in one call (paginated by `gh`
itself), which is both simpler and cheaper than the repo-by-repo enumeration
`gather_activity.py` does for personal activity.

### Processing

1. Convert each PR's `mergedAt` (UTC) to local-tz `YYYY-MM-DD` (reuse the same `LOCAL_TZ`
   conversion logic as `gather_activity.py`).
2. Group into:
   - `days[date] -> total count`
   - `days[date][repo] -> count`
3. Emit both a JSON mode (`--json` flag, for the skill to consume) and a rendered markdown table:
   - Daily totals table
   - Per-day, per-repo breakdown table

### Caching

Same rule as `gather_activity.py`: cache to `.claude/skills/team-activity/cache/<start>_<end>.json`.
Closed date ranges (end date before today) cache indefinitely; ranges including today/future
expire after 1 hour. This lets `team-activity` be re-run cheaply within a session.

### CLI interface

```
python3 scripts/gather_pr_merges.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--json] [--no-cache] [--cache-dir PATH]
```

Mirrors `gather_activity.py`'s flags for consistency.

## Component: Linear comments (MCP-driven, no script)

### Prerequisite (one-time setup)

A Linear MCP server must be connected before this part of the skill can run. `SKILL.md` documents
this as a setup step (adding the server via `claude mcp add`, then authenticating) and the skill
checks for Linear MCP tool availability before attempting to use it.

### Runtime flow

Since the exact tool names/shapes exposed by the connected Linear MCP server aren't known until
it's set up, `SKILL.md` describes the **goal** rather than hardcoding tool calls:

1. Find Linear issues/tickets updated within the date range, across all teams in the workspace
   (not filtered to one team).
2. For each such issue, fetch its comments.
3. Filter to comments actually created within the date range (an issue can be "updated" in-range
   while having older comments, or vice versa).
4. Tally:
   - Comment count per ticket (ticket identifier, e.g. `ENG-231`)
   - Comment count per day (sum across all tickets)

### Output

Two markdown tables:
- **Linear Comments by Day** — day, total comment count
- **Linear Comments by Ticket** — ticket ID, comment count (sorted descending by count)

## Combined report format

```
## Team Activity: <start> - <end>

### PRs Merged
| Day       | Total | By Repo                  |
|-----------|-------|---------------------------|
| Mon 07/06 | 4     | repo-a: 3, repo-b: 1      |
...

### Linear Comments by Day
| Day       | Comments |
|-----------|----------|
| Mon 07/06 | 12       |
...

### Linear Comments by Ticket
| Ticket  | Comments |
|---------|----------|
| ENG-231 | 5        |
...
```

If the Linear MCP server isn't connected or a call fails, the PR section is still shown, with a
note that the Linear section was skipped and why.

## Error handling

- `gh search prs` failures: warn to stderr, treat as zero results for the affected page rather
  than crashing (same pattern as `gh_api`/`gh_search` in `gather_activity.py`).
- Linear MCP unavailable/not connected: skip the Linear section, tell the user how to connect it,
  still print the PR section.
- Large date ranges (e.g. > 90 days): the skill warns before running, since org-wide PR search and
  per-issue comment fetching both scale with range size; suggest narrowing the range.
- Missing/malformed dates: reuse `weekly-activity`'s default (current week, Monday through today)
  when no date range is given.

## Testing

This repo has no automated test suite (skills-only, no CI) — verification is manual:

- Run `gather_pr_merges.py` for a known past week and spot-check the daily/repo totals against
  GitHub's web search UI (`merged:<range> org:dragonflyic`).
- Spot-check one Linear ticket's comment count against the Linear UI for the same date range.
- Confirm the combined report degrades gracefully when Linear MCP is intentionally disconnected.

## Open questions / risks

- The exact Linear MCP tool surface is unknown until connected — `SKILL.md` will need a short
  adjustment pass once the server is added and its actual tool names are visible.
- `gh search prs` result caps: GitHub search API results may be capped (e.g. 1000 results); a
  very active month across the whole org could theoretically hit this. Not a concern for typical
  weekly/monthly ranges but worth a comment in the script.
