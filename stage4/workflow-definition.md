# Workflow definition: `weekly-log`

Three validated Stage 3 skills wired into one end-to-end workflow, driven by
`workflow/run_weekly_log.py` and invocable as `/weekly-log`.

```
 s1_activity ──g1──▶ s2a_plan ──g2──▶ s2b_enter ──g3──▶ [P1 human] ──▶ s2c_submit
 (weekly-activity)   (timelogger      (timelogger       submit?        (timelogger
                      --plan-only)     --enter-only)                    --submit-only)
                                                                             │
                                                                             ▼
                                                     g4 ──▶ [P2 human, only if not self-chat] ──▶ s3_send
                                                                                                 (teams-messenger)
```

## The Stage 3 agents

| Skill | Deterministic core | Unit tests | Prompt eval (`evals/cases.json`, graded by `evals/run_skill_eval.py`) |
|---|---|---|---|
| `weekly-activity` | `scripts/gather_activity.py` (GitHub Events + issues/PRs, cached) | `tests/` (8 files) | 3 cases: populated week, natural-language window, empty future week. Deterministic graders `ScriptExecuted`, `DayCoverage`, `GroundedIdentifiers` + one rubric judge on the TEC report. |
| `workday-timelogger` | `scripts/plan_entries.py` (hour split, ticket distribution, comment rules) | `tests/test_plan_entries.py` (12) | 3 cases (plan-only): split day with real activity, future-week placeholder, natural-language request. Graded by `ScriptExecuted`, `NoCommandContaining` (no browser), `PlanMatches` on the written plan file, one judge. Last run: 100%. |
| `teams-messenger` | `scripts/to_teams_html.py` (markdown → Teams HTML, clipboard) | `tests/test_to_teams_html.py` (7) | 3 cases: dry-run rich message, live send to self-chat, unknown target. Graded by `ScriptExecuted`, `NoCommandContaining` (no Send on dry-run / unknown target), judge. Last run: 100%. |
| `weekly-log` (the workflow itself) | `workflow/` package | `workflow/tests/` (35) | 3 cases: test dry-run skipping Workday, test dry-run with planning, refusal to forge the approval. Graded by `ScriptExecuted`, `NoCommandContaining`, `AuditOutcome` (reads the run's own `audit.jsonl`), judge. |

All three agents run without manual correction in the harness: each is invoked
one phase at a time with an explicit input file and output file, and the
harness never asks the model to fix its own output.

## Steps and handoffs

Every handoff is a file in `workflow/runs/<run_id>/`. The harness never scrapes
step prose except for `s1_activity`, whose whole reply *is* the YAML artifact
(saved verbatim, then validated by g1).

| Step | Invocation (a headless `claude -p` turn) | Reads | Writes |
|---|---|---|---|
| `s1_activity` | `/weekly-activity <start>..<end>` | GitHub (via `gh`), cache | `s1_activity.yaml` — `range`, one `days[]` entry per date with `items[].ref/title`, and `summary` (TEC report HTML) |
| `s2a_plan` | `/workday-timelogger --plan-only --hours … --week-start … --activity s1_activity.yaml --today … --out s2a_plan.json` | `s1_activity.yaml` | `s2a_plan.json` — `entries[] {date, day, entry: Reg/Extra, hours, comment, tickets}` |
| `s2b_enter` | `/workday-timelogger --enter-only s2a_plan.json --out s2b_enter.json` | `s2a_plan.json`, Workday UI | `s2b_enter.json` — per-entry `status`, per-day `totals` read back from Workday, `screenshot` |
| `p1_submit_timesheet` | harness punch-out | plan table, totals, screenshot | `approved-p1_submit_timesheet.sentinel` (human) |
| `s2c_submit` | `/workday-timelogger --submit-only` | Workday UI | submission (hook allows the Submit click only with the sentinel) |
| `g4` + `p2_send_to_others` | harness | `s1_activity.yaml` | `s3_message.html` (= the `summary`), `teams-target.txt` |
| `s3_send` | `/teams-messenger [--dry-run] --message-file s3_message.html "<target>"` | `s3_message.html`, Teams UI | the posted message (hook allows the Send click only for the self-chat or with the sentinel) |

## Branching

| Condition | Behaviour |
|---|---|
| any guardrail fails | run ends `failed`, `origin_step` = the step whose output failed; later steps never run |
| a step's turn errors or times out | run ends `failed` at that step |
| `--skip-workday` | s1 → g1 → g4 → s3 (hours already submitted) |
| `--skip-teams` | stop after s2c |
| `--dry-run` | s2b/g3/P1/s2c skipped (plan still built and checked); s3 runs with `--dry-run` (paste, verify, no Send) |
| `--teams-target` ≠ self-chat | P2 punch-out before s3 |
| `--test` | week = next Mon–Tue, `Mon 8, Tue 8`, self-chat, `mode: test` |
| punch-out, no TTY | run ends `awaiting_human`; `--resume <run_id>` continues after the sentinel is created, reusing every completed step's output |
| punch-out, TTY | harness prompts `approve` / `reject`; `reject` ends the run `rejected_by_human` |

## Where things live

- Harness: `workflow/run_weekly_log.py` (sequence), `workflow/prompts.py` (step prompts), `workflow/steps.py` (headless turn + usage parsing), `workflow/audit.py`, `workflow/report.py`.
- Guardrails: `workflow/guardrails/`, hook `.claude/hooks/require_sentinel.py` (registered in `.claude/settings.json`).
- Skill wrapper: `.claude/skills/weekly-log/SKILL.md`.
- Design spec: `docs/superpowers/specs/2026-09-13-weekly-log-stage4-workflow-design.md`.
