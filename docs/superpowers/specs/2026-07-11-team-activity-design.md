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
    gather_linear_comments.py
  cache/                      # gitignored, created at runtime
```

- `gather_pr_merges.py` handles the GitHub side: a standalone, cacheable, deterministic script,
  following the same conventions as `weekly-activity/scripts/gather_activity.py`.
- `gather_linear_comments.py` handles the Linear side: a standalone script authenticated via a
  personal API key (`LINEAR_API_KEY` env var, already added to `.env`), calling Linear's GraphQL
  API directly. No MCP dependency.
- `SKILL.md` orchestrates both parts and renders one combined markdown report.

### Why GraphQL instead of MCP

The design originally called for Linear MCP tools, but no Linear MCP server was connected. A
personal API key was added to `.env` and tested directly against `https://api.linear.app/graphql`
(confirmed working: `{ viewer { id name email } }` resolved successfully, auth via the
`Authorization` header with the raw key, no `Bearer` prefix). Since a direct GraphQL script gives
deterministic, cacheable output consistent with the GitHub side — and avoids depending on an
MCP server's unknown/unstable tool surface — the design now uses GraphQL directly instead of MCP.

## Component: `gather_pr_merges.py` (GitHub, org-wide PR merges)

### Why not reuse `gather_activity.py`'s approach

`gather_activity.py` discovers repos via the Events API filtered to one actor
(`users/{GH_USERNAME}/events`), which only surfaces repos *that user* touched. `team-activity`
needs merged PRs from **any** author across **all** dragonflyic repos, so repo discovery via a
single user's event stream doesn't work.

### Approach

Use a single paginated GitHub GraphQL search across the whole org, instead of enumerating repos
and querying each one individually. `gh search prs`'s `--json` output was tried first but does
not expose `mergedAt` (only day-granularity `--merged-at` filtering, which would force UTC-day
bucketing instead of local-tz). `gh api graphql` with a `search(type: ISSUE)` query does return a
full `mergedAt` timestamp, confirmed live against the real org:

```
gh api graphql -f query='
  query($q: String!, $after: String) {
    search(query: $q, type: ISSUE, first: 50, after: $after) {
      issueCount
      pageInfo { hasNextPage endCursor }
      nodes {
        ... on PullRequest {
          number
          title
          mergedAt
          repository { name }
        }
      }
    }
  }' -f q='org:dragonflyic is:pr is:merged merged:<start>..<end>'
```

Paginate with `after: <endCursor>` while `hasNextPage` is true. This returns every merged PR in
the org for the date range with exact merge timestamps, in a small number of calls (one per page
of 50) — still far cheaper than the repo-by-repo enumeration `gather_activity.py` does for
personal activity.

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

## Component: `gather_linear_comments.py` (Linear, org-wide comment volume)

### Prerequisite

`LINEAR_API_KEY` (a personal API key from Linear Settings → Security & access → Personal API
keys) must be set — already added to the project's `.env`. The script loads it from the
environment (loading `.env` itself, or relying on it being exported — consistent with how the
rest of the repo handles local env/config).

### Auth

`POST https://api.linear.app/graphql` with header `Authorization: <raw key>` (no `Bearer`
prefix) — confirmed working via a manual `viewer { id name email }` test query.

### Query

Linear's GraphQL API exposes a top-level `comments` collection that can be filtered and paginated
server-side, without needing to first enumerate issues:

```graphql
query($after: String, $gte: DateTimeOrDuration!, $lte: DateTimeOrDuration!) {
  comments(
    first: 100
    after: $after
    filter: { createdAt: { gte: $gte, lte: $lte } }
    orderBy: createdAt
  ) {
    nodes {
      id
      createdAt
      issue { identifier title team { key name } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
```

This covers every team in the workspace by default (no team filter applied) and returns
comments already scoped to the date range — no client-side filtering of an issue's full comment
history needed, and no separate "list issues then fetch comments per issue" round-trips.

### Processing

1. Page through `comments` until `hasNextPage` is false, converting each `createdAt` (UTC) to
   local-tz `YYYY-MM-DD` (reuse the same conversion logic as the GitHub script).
2. Tally:
   - Comment count per ticket (`issue.identifier`, e.g. `DRA-221`)
   - Comment count per day (sum across all tickets)

### Output

JSON mode (for the skill to consume) plus two rendered markdown tables:
- **Linear Comments by Day** — day, total comment count
- **Linear Comments by Ticket** — ticket ID, comment count (sorted descending by count)

### Caching

Same rule as `gather_pr_merges.py`: cache to
`.claude/skills/team-activity/cache/linear_<start>_<end>.json`, closed ranges cached indefinitely,
current/future ranges expire after 1 hour.

### CLI interface

```
python3 scripts/gather_linear_comments.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--json] [--no-cache] [--cache-dir PATH]
```

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

If `LINEAR_API_KEY` is missing or a GraphQL call fails, the PR section is still shown, with a
note that the Linear section was skipped and why.

## Error handling

- `gh search prs` failures: warn to stderr, treat as zero results for the affected page rather
  than crashing (same pattern as `gh_api`/`gh_search` in `gather_activity.py`).
- `LINEAR_API_KEY` missing or GraphQL request failing (auth error, network error, non-200):
  print a warning to stderr, skip the Linear section, still print the PR section.
- Large date ranges (e.g. > 90 days): the skill warns before running, since org-wide PR search and
  per-issue comment fetching both scale with range size; suggest narrowing the range.
- Missing/malformed dates: reuse `weekly-activity`'s default (current week, Monday through today)
  when no date range is given.

## Testing

This repo has no automated test suite (skills-only, no CI) — verification is manual:

- Run `gather_pr_merges.py` for a known past week and spot-check the daily/repo totals against
  GitHub's web search UI (`merged:<range> org:dragonflyic`).
- Spot-check one Linear ticket's comment count against the Linear UI for the same date range.
- Confirm the combined report degrades gracefully when `LINEAR_API_KEY` is unset/invalid.

## Open questions / risks

- `gh search prs` result caps: GitHub search API results may be capped (e.g. 1000 results); a
  very active month across the whole org could theoretically hit this. Not a concern for typical
  weekly/monthly ranges but worth a comment in the script.
- Linear GraphQL pagination/rate limits: personal API keys are subject to Linear's standard rate
  limits; a very large date range could require many pages of 100 comments each. Same "warn on
  large ranges" mitigation as the GitHub side covers this.
- `.env` now holds `LINEAR_API_KEY` and has been added to `.gitignore` to prevent accidental
  commits; the script must never print or log the key value.
