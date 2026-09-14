# Guardrails

All guardrails are automated and sit **between** steps: the harness runs them on
the file one step wrote before the next step may read it. None lives inside a
skill, and no human review happens between steps — the only human touchpoints
are the two punch-outs, which are decisions, not reviews (see
`punch-out-evidence.md`).

## Deterministic checks (Python, `workflow/guardrails/`, 18 unit tests)

| Id | Between | What it rejects |
|---|---|---|
| `g1_activity_check` | s1 → s2a | YAML that does not parse; `range` ≠ requested window; a `days` list that is not exactly one entry per date; malformed refs; **any `repo#N` not present in the gathered GitHub data for that window** (fabrication) or **any gathered ref missing from the YAML** (silent compression); a TEC report missing a section or with sections out of order; leftover `<!-- -->` template comments; any ticket number in the report. |
| `g2_plan_check` | s2a → s2b | Planned days ≠ requested days; per-day total ≠ requested hours; > 8 h regular, > 3 h extra, > 11 h total; entry kinds other than `[Reg]` / `[Reg, Extra]`; empty or > 255-char comments; `(unknown #N)` tickets; a future day with anything but the placeholder; **any ticket in a comment that weekly-activity did not report for that day**. |
| `g3_entry_check` | s2b → P1 | An entry whose status is not `Entered` / `Already filled` / `Locked`; a planned entry with no status; **a per-day total read back from Workday's weekly view that differs from the plan**. |
| `g4_message_check` | s1 → s3 | A message whose whitespace-normalised SHA-256 differs from the step-1 `summary` (nothing may be edited between the report and Teams); any ticket number. |

## Adversarial review agent (`g1_adversarial`)

A second model (Haiku, no tools) is handed the raw gathered data and the TEC
report and told to list every claim the data does not support, as a JSON array.
Only an empty array passes. Its prompt is the fixed `RUBRIC` in
`workflow/guardrails/adversarial.py`; its tokens and cost are recorded in the
audit log like any step (`kind: step, id: g1_adversarial`).

## Hook + sentinel files (runtime enforcement)

`.claude/hooks/require_sentinel.py` is a `PreToolUse` hook on every Bash call
(`.claude/settings.json`). Inside a harness run (`WEEKLY_LOG_RUN_DIR` set):

- a `-s=workday` click on **Submit / Confirm** needs `approved-p1_submit_timesheet.sentinel`;
- a `-s=teams` click on **Send**, or an Enter / ⌘-Enter key press, needs
  `approved-p2_send_to_others.sentinel` when `teams-target.txt` is not the self-chat;
- a click by element ref is resolved against every Playwright snapshot taken in
  the last 15 minutes (`.playwright-cli/page-*.yml`); a ref no snapshot names is
  refused until a fresh snapshot is taken, so changing selector cannot evade it;
- every decision is appended to `<run_dir>/hook.log`.

Blocked calls return exit 2 with a message the model sees; the harness records
them as `blocked_calls` in the step's audit record, and a blocked click after an
approval fails the run (`hook_p1` / `hook_p2` records).

Outside a harness run the hook allows everything, so the interactive skills keep
their existing chat-based confirmation and unrelated sessions are unaffected.

Tests: `workflow/tests/test_hook.py` (13) and the live bypass test
`workflow/test_bypass.py`, whose output is `punch-out-evidence.md`.

## Failure ≠ punch-out

| | Guardrail failure | Punch-out |
|---|---|---|
| trigger | a check on a step's output is false | the workflow reaches a decision reserved for a human |
| code path | `do_guardrail` → `StopRun(failed, origin_step)` | `punch_out` → sentinel / prompt |
| audit record | `kind: guardrail, outcome: failed, reason, origin_step` | `kind: punchout, outcome: approved / awaiting_human / rejected_by_human` |
| run outcome | `failed` | `awaiting_human` (resumable) or `rejected_by_human` |
| counted in the success rate as | a failure | not decided (awaiting) / not a success (rejected) |
