# weekly-log: a Stage 4 workflow over three Stage 3 skills

**Status:** approved design
**Owner:** Tonan Salas
**Date:** 2026-09-13

## Summary

Chain three existing skills into one evaluated, guarded, auditable workflow:

1. `weekly-activity` gathers GitHub activity and writes the TEC status report.
2. `workday-timelogger` plans and enters the week's hours into Workday.
3. `teams-messenger` posts the TEC report to a Teams chat.

The workflow is driven by a Python harness (`workflow/run_weekly_log.py`) that runs each
step as a headless Claude Code turn (`claude -p --output-format stream-json`), runs
deterministic guardrails and an adversarial reviewer between steps, stops at two human
punch-out points, and writes a structured JSONL audit log with per-step model, tokens and
cost. A thin `/weekly-log` skill launches the harness so it stays invocable from Claude
Code. `workflow/report.py` computes the end-to-end success rate and trend from the logs.

The Stage 4 certification asks for five artifacts (workflow definition, guardrails,
punch-out evidence, end-to-end success rate, audit trail). Each maps to a concrete file
listed under "Deliverable" below.

## Vocabulary

- **run** — one invocation of the harness for one target week. Identified by
  `run_id = <UTC timestamp>-<short random>`. Everything a run produces lives in
  `workflow/runs/<run_id>/`.
- **step** — one headless Claude turn executing one skill (or one phase of one skill).
  Step ids: `s1_activity`, `s2a_plan`, `s2b_enter`, `s3_send`.
- **guardrail** — an automated check that runs *between* steps, never inside one. Ids:
  `g1_activity_check`, `g1_adversarial`, `g2_plan_check`, `g3_entry_check`,
  `g4_message_check`. A failing guardrail fails the run at that step.
- **punch-out** — a decision the harness will not make: the run pauses and waits for a
  human. Ids: `p1_submit_timesheet`, `p2_send_to_others`. A punch-out is not a failure
  and is recorded with a different outcome value.
- **sentinel** — a file whose presence is the human's approval:
  `workflow/runs/<run_id>/approved-<punchout_id>.sentinel`. Written only by the human
  (or by the harness after the human types `approve` at its prompt). The `PreToolUse`
  hook refuses to run the committing browser action unless the sentinel exists.

## Goals / non-goals

**Goals**
- Every step, guardrail and punch-out lands in one audit log with step id, model, input
  tokens, output tokens, cost in USD, duration, and outcome.
- Guardrails are deterministic where the expectation is literal; the one LLM guardrail
  (adversarial reviewer) is graded pass/fail on a fixed rubric.
- Punch-outs are enforced by a hook plus sentinel, and the enforcement is tested by
  attempting to bypass it and recording the block.
- An end-to-end success rate computed from real runs, with a per-run trend.
- `workday-timelogger` and `teams-messenger` reach the same Stage 3 bar as
  `weekly-activity`: deterministic logic in a tested script, `evals/cases.json` graded by
  `evals/run_skill_eval.py`.

**Non-goals**
- Replacing the interactive skills. They keep working on their own; the harness only
  adds a headless entry point and a couple of flags.
- Real-time streaming of spans to Logfire during a run. The audit log is local JSONL;
  eval runs still go to Logfire through the existing runner.
- Scheduling. The workflow is run on demand.

## Workflow definition

```
weekly-activity ──g1──▶ timelogger plan ──g2──▶ timelogger enter ──g3──▶ [P1] submit
                                                                          │
                                                                          ▼
                                                             g4 ──▶ [P2?] ──▶ teams send
```

| Step | Skill / phase | Input | Output artifact |
|---|---|---|---|
| `s1_activity` | `weekly-activity <start>..<end>` | week window | `s1_activity.yaml` (days + `summary` HTML) |
| `s2a_plan` | `workday-timelogger` Phases 1–2, `--plan-only` | hours string, `s1_activity.yaml` | `s2a_plan.json` (entries + issues) |
| `s2b_enter` | `workday-timelogger` Phases 3–6, `--enter-only` | `s2a_plan.json` | `s2b_enter.json` (per-entry status + weekly totals read back from Workday, screenshot path) |
| `p1_submit_timesheet` | harness punch-out | plan + screenshot | sentinel or `awaiting_human` |
| `s2c_submit` | `workday-timelogger` Phase 7 submit click only | sentinel | `s2c_submit.json` |
| `s3_send` | `teams-messenger` | `s1_activity.yaml` summary, target | `s3_send.json` (chat name, timestamp) |

**Branching**
- `--skip-workday`: runs s1 → g1 → g4 → s3 only. Used when hours were already submitted.
- `--skip-teams`: stops after s2c. Used when the report is not wanted.
- `--teams-target` other than the self-chat triggers `p2_send_to_others` before s3.
- Any guardrail failure ends the run with `outcome: failed`, `origin_step` set to the step
  whose output failed the check. Later steps do not run.
- A punch-out with no sentinel ends the harness process with `outcome: awaiting_human`.
  Re-running with `--resume <run_id>` after writing the sentinel continues from the
  paused step; earlier step outputs are reused from the run directory.

**Handoffs** are files in the run directory, not chat text. Each step's prompt names the
exact input file it must read and the exact output file it must write. The harness never
scrapes step prose.

**Test mode**: `--test` sets the Workday target to the Monday and Tuesday of the coming
week with the hours `Mon 8, Tue 8`, sets the Teams target to `Tonan Salas (You)`, and
tags the run `mode: test`. `workflow/cleanup_workday.py` deletes the two test entries
after a run.

## Guardrails

All guardrails are Python in `workflow/guardrails/` and run in the harness process.
None is inside a skill. Each returns `(passed, reason)` and is logged.

| Id | Between | Check |
|---|---|---|
| `g1_activity_check` | s1 → s2a | YAML parses; `range` matches the requested window; one `days` entry per date; every `ref` (`repo#N`) exists in `weekly-activity`'s cached JSON for that window (fabrication check, reuses the cache the script already writes); `summary` HTML carries the eight TEC section markers in order; no `#\d+` or `DRA-\d+` in the summary; no `<!-- -->` comments survive. |
| `g1_adversarial` | s1 → s2a | A Haiku turn (no tools) is given the cached JSON and the `summary` HTML and asked to list every claim in the report that the JSON does not support. Empty list passes. Non-empty fails with the list as the reason. |
| `g2_plan_check` | s2a → s2b | Every planned day is in the requested hours; per-day total equals the requested hours; no entry > 8 h regular or > 3 h extra; total ≤ 11; comments ≤ 255 chars; every ticket in a comment appears in `s1_activity.yaml` for that day (or the comment is exactly `Activity placeholder` for a future day); no `(unknown #N)` tickets. |
| `g3_entry_check` | s2b → p1 | For each planned day, the hours total read back from the Workday weekly view equals the planned total; every planned entry has status `Entered`, `Already filled` or `Locked`; nothing else. |
| `g4_message_check` | s2c/s1 → s3 | SHA-256 of the message HTML the harness hands to s3 equals SHA-256 of the `summary` from `s1_activity.yaml`; the HTML contains no ticket numbers. |

**Hook + sentinel (runtime enforcement)**

`.claude/hooks/require_sentinel.py`, registered as a `PreToolUse` hook on `Bash` in
`.claude/settings.json`. It reads the tool input, and if the command matches one of the
committing actions:

- Workday: a `-s=workday` Playwright command whose click target is `Submit` or `Confirm`
  (role-name or ref preceded by a snapshot line naming Submit is not detectable, so the
  skill's submit step is required to click by role name: `click 'button "Submit"'`).
- Teams: a `-s=teams` Playwright command that clicks `button "Send`.

then it requires `WEEKLY_LOG_RUN_DIR` to be set and `approved-<id>.sentinel` to exist
there. Otherwise it exits 2 with a message naming the missing sentinel, which blocks the
tool call and is fed back to the model. When `WEEKLY_LOG_RUN_DIR` is unset (interactive
use outside the harness) the hook does not block, so the interactive skills keep their
existing chat-based confirmation.

**Bypass test** (`workflow/test_bypass.py`): with a run dir and no sentinel, run a
headless turn whose prompt orders it to click Submit on the Workday weekly view. Expected:
the hook blocks, the turn ends without submitting, and the stream-json shows the
`tool_result` with `is_error: true` and the hook's message. The script writes
`stage4/punch-out-evidence.md` with the transcript excerpt. The same test runs for the
Teams Send button with a message to the self-chat.

## Punch-outs

| Id | Decision | Why a human | Evidence shown |
|---|---|---|---|
| `p1_submit_timesheet` | Submit this week's Workday timesheet | Payroll and billing record; wrong hours are costly to reverse | plan table, read-back totals, screenshot path |
| `p2_send_to_others` | Post the report to a chat other than the self-chat | Other people read it; cannot be unsent | rendered HTML, target name |

The harness prints the evidence and, if stdin is a TTY, asks for `approve` / `reject`.
`approve` writes the sentinel and continues. `reject` ends the run with
`outcome: rejected_by_human`. Non-TTY: ends with `outcome: awaiting_human` and prints the
sentinel path and the `--resume` command.

Failures and punch-outs are separate code paths with separate outcome values:

| outcome | meaning |
|---|---|
| `success` | all steps ran, all guardrails passed, all punch-outs approved |
| `failed` | a step errored or a guardrail failed; `origin_step` set |
| `awaiting_human` | paused at a punch-out, no decision yet |
| `rejected_by_human` | a punch-out was declined |

## Audit trail

`workflow/runs/<run_id>/audit.jsonl`, one record per event. Every record carries
`run_id`, `ts`, `kind` (`step` / `guardrail` / `punchout` / `run`), `id`, `outcome`.
Step records add `model`, `input_tokens`, `output_tokens`,
`cache_read_tokens`, `cache_creation_tokens`, `cost_usd`, `duration_ms`,
`num_turns`, `session_id`, `input_path`, `output_path`, `raw_path` (the full stream-json).
Guardrail records add `passed`, `reason`, `checked_output` (the step output path).
Punch-out records add `sentinel_path`, `decision`, `decided_by`.

Token and cost values come from the headless turn's `result` event (`usage`,
`modelUsage`, `total_cost_usd`), which Claude Code emits per turn. When a step uses more
than one model (a skill dispatching a Haiku subagent), `modelUsage` is stored per model
and the step's `model` field lists all of them.

Tracing a failure: `report.py --run <run_id>` prints the records in order and names the
first record with a non-passing outcome and its `origin_step`.

## End-to-end success rate

`workflow/report.py` reads every `audit.jsonl` under `workflow/runs/` and prints:

- total runs, successes, end-to-end success rate (`success / (runs − awaiting_human)`);
- a per-run table: run id, mode, outcome, origin step if failed, total cost, total tokens;
- a per-step pass rate table;
- a trend line: cumulative success rate after each run in order.

It also writes `stage4/success-report.md`. The Stage 4 number is the end-to-end rate, not
per-step accuracy. Three real test runs are planned for the first report.

## Stage 3 upgrades for the two remaining skills

**workday-timelogger**
- `scripts/plan_entries.py`: pure function from (hours string, activity YAML, today) to
  the plan JSON (split, ticket distribution, comment building and the 255-char fallback,
  `(unknown #N)` filtering, future-day placeholders). `tests/` covers each rule.
- SKILL.md Phase 2 calls the script instead of doing the arithmetic in prose; gains
  `--plan-only`, `--enter-only <plan.json>`, and `--submit-only` phase flags used by the
  harness. Phase 7's submit click is changed to click by role name so the hook can see it.
- `evals/cases.json`: plan-only cases (a >8 h day, a future week, a comment overflow)
  graded by `ScriptExecuted` plus a new deterministic `PlanMatches` evaluator over the
  produced plan file, and one `ClaudeCLIJudge` case for the confirmation tables.

**teams-messenger**
- `scripts/to_teams_html.py`: markdown/HTML → Teams-safe HTML, and a `--clipboard` flag
  that runs the Swift `NSPasteboard` step. `tests/` covers the conversion rules.
- SKILL.md Phase 3 calls the script; gains `--dry-run` (everything except the Send click).
- `evals/cases.json`: dry-run cases graded by `ScriptExecuted` (script called, paste
  verified) and a judge case on the confirmation message; one live case to the self-chat.

**weekly-activity**: unchanged.

**The workflow as a Stage 3 prompt**: `.claude/skills/weekly-log/evals/cases.json`
covers the harness entry (`--test --dry-run` end to end, `--skip-workday`, and a case
where s1 is fed a tampered YAML so g1 must fail) graded by `ScriptExecuted` and a new
`AuditOutcome` evaluator that reads the run's `audit.jsonl`.

`evals/run_skill_eval.py` gains the two new evaluators (`PlanMatches`, `AuditOutcome`)
and nothing else.

## File layout

```
.claude/
  settings.json                          # + PreToolUse hook registration
  hooks/require_sentinel.py
  skills/
    weekly-log/SKILL.md                  # thin: explains flags, runs the harness
    weekly-log/evals/cases.json
    workday-timelogger/{SKILL.md, scripts/plan_entries.py, tests/, evals/cases.json}
    teams-messenger/{SKILL.md, scripts/to_teams_html.py, tests/, evals/cases.json}
workflow/
  run_weekly_log.py                      # harness
  steps.py                               # step prompt builders + stream-json parsing
  guardrails/{activity.py, plan.py, entry.py, message.py, adversarial.py}
  audit.py                               # JSONL writer/reader
  report.py                              # success rate + trend + failure trace
  test_bypass.py                         # punch-out enforcement test
  cleanup_workday.py                     # delete test-mode entries
  tests/                                 # pytest for guardrails, audit, report, parsing
  runs/                                  # gitignored except stage4 evidence copies
stage4/
  README.md                              # index for the certification ZIP
  workflow-definition.md
  guardrails.md
  punch-out-evidence.md
  success-report.md
  audit/                                 # copied audit.jsonl of the evidence runs
docs/superpowers/specs/2026-09-13-weekly-log-stage4-workflow-design.md
```

## Testing

- pytest for every pure module (guardrails, plan builder, HTML converter, audit
  reader/writer, report, stream-json parsing) with fixtures.
- Skill evals via the existing runner for the two upgraded skills and the workflow skill.
- Bypass test run for real and its output kept as evidence.
- Three real end-to-end runs in `--test` mode (Workday Sep 14–15 2026, self-chat), each
  followed by `cleanup_workday.py`. Their audit logs are the success-report input.

## Decisions taken

- Orchestration: Python harness + thin skill (approved 2026-09-13).
- Production Teams target stays the self-chat until changed (approved).
- Three evidence runs (approved).
- Adversarial reviewer runs on Haiku for cost; its rubric is fixed text in
  `guardrails/adversarial.py`, graded by whether the returned claim list is empty.
- The hook only enforces inside a harness run (`WEEKLY_LOG_RUN_DIR` set). Interactive use
  keeps the existing chat confirmation. This keeps the hook from breaking unrelated
  sessions while still being active runtime enforcement for the workflow.

## Open questions

- Workday's UI for deleting an entry has not been driven before; `cleanup_workday.py`
  will be written after one manual discovery pass.
- Whether `claude -p` respects project `PreToolUse` hooks in this version is verified in
  the bypass test before anything depends on it.
