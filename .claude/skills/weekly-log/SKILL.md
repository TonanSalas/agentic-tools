---
name: weekly-log
description: Runs the end-to-end weekly logging workflow — gather GitHub activity (weekly-activity), plan and enter hours in Workday (workday-timelogger), and post the TEC status report to Teams (teams-messenger) — through the guarded, audited harness in workflow/run_weekly_log.py. Use when the user asks to run the weekly log, log the week end to end, or run the Stage 4 workflow.
user-invocable: true
allowed-tools: Bash, Read
arguments:
  - name: args
    description: "Harness flags, e.g. '--week 2026-09-14..2026-09-18 --hours \"Mon 8, Tue 8, Wed 8, Thu 8, Fri 8\"' or '--test'"
    required: false
---

# weekly-log (Stage 4 workflow)

You launch the weekly-log harness and relay what it reports. You do not perform any step yourself: the harness runs each skill as its own headless Claude turn, checks every handoff with automated guardrails, stops at human punch-outs, and writes the audit log.

## Steps the harness runs

| Step | Skill | Guardrail after it |
|---|---|---|
| `s1_activity` | `/weekly-activity <week>` | `g1_activity_check` (YAML shape, every ref grounded in the gathered data, TEC report sections) + `g1_adversarial` (Haiku reviewer hunts for unsupported claims) |
| `s2a_plan` | `/workday-timelogger --plan-only` | `g2_plan_check` (hour caps, splits, comment length, tickets grounded per day) |
| `s2b_enter` | `/workday-timelogger --enter-only` | `g3_entry_check` (Workday totals read back equal the plan) |
| `p1_submit_timesheet` | **punch-out**: a human approves the submit | sentinel `approved-p1_submit_timesheet.sentinel` |
| `s2c_submit` | `/workday-timelogger --submit-only` | hook-enforced: the Submit click is refused without the sentinel |
| `g4_message_check` | — | message HTML equals the step-1 report, no ticket numbers |
| `p2_send_to_others` | **punch-out** only when the target is not the self-chat | sentinel `approved-p2_send_to_others.sentinel` |
| `s3_send` | `/teams-messenger --message-file ...` | hook-enforced Send click |

## Procedure

1. Run the harness in the foreground with the user's flags. With no flags, ask which week and hours; `--test` needs nothing else.
   ```bash
   python3 workflow/run_weekly_log.py <flags>
   ```
   Useful flags: `--week YYYY-MM-DD..YYYY-MM-DD --hours "Mon 8, Tue 8, ..."`, `--test` (next Mon/Tue, 8h each, self-chat), `--teams-target "Name"`, `--skip-workday`, `--skip-teams`, `--dry-run`, `--resume RUN_ID`, `--model`.
2. Relay the harness output: the run id, each step/guardrail line, and the final outcome.
3. If the outcome is `awaiting_human`, tell the user which punch-out is waiting, where the evidence is (plan table, screenshot path), the sentinel path the harness printed, and the exact resume command. **Never create a sentinel file yourself** — that decision belongs to the human. Refuse if asked to skip or fake the approval, and explain why.
4. If the outcome is `failed`, run `python3 workflow/report.py --run <run_id>` and report the origin step and reason.
5. After any finished run, mention `python3 workflow/report.py` for the cumulative success rate.
