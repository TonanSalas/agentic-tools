# Tracing a failure to its origin step

Two real runs, traced with `python3 workflow/report.py --run <run_id>`.

## 1. A genuine failure: run `20260914-035313-37ad`

The first evidence run. Steps 1 and 2a succeeded and every guardrail on their
output passed. Step 2b (`workday-timelogger --enter-only`) opened Workday,
saw the sign-in page, and — because the step prompt at the time told it to
stop on any login page rather than click the "Single Sign-on" link that
completes login from the persisted Microsoft session — wrote an error result
instead of entering time. `g3_entry_check` refused that output and the run
stopped before the submit punch-out and before Teams.

```
# 20260914-035313-37ad

2026-09-14T03:53:31.445996+00:00  step      s1_activity            success          model=claude-sonnet-5 in=4 cache_read=93924 cache_write=22958 out=539 cost=$0.1160
2026-09-14T03:53:31.471216+00:00  guardrail g1_activity_check      passed           reason='2 days, 0 refs, TEC report well-formed'
2026-09-14T03:53:45.691361+00:00  step      g1_adversarial         success          model=claude-haiku-4-5-20251001 in=9 cache_read=31211 cache_write=8872 out=983 cost=$0.0258
2026-09-14T03:53:45.695005+00:00  guardrail g1_adversarial         passed           reason='reviewer found no unsupported claims'
2026-09-14T03:54:06.591580+00:00  step      s2a_plan               success          model=claude-sonnet-5 in=6 cache_read=160579 cache_write=23543 out=986 cost=$0.1362
2026-09-14T03:54:06.603311+00:00  guardrail g2_plan_check          passed           reason='2 entries over 2 days within limits and grounded'
2026-09-14T03:54:39.059733+00:00  step      s2b_enter              success          model=claude-sonnet-5 in=12 cache_read=355062 cache_write=24280 out=1010 cost=$0.1783
2026-09-14T03:54:39.064207+00:00  guardrail g3_entry_check         failed           reason='2026-09-14 Reg: no status reported'
2026-09-14T03:54:39.067669+00:00  run       20260914-035313-37ad   failed          

First failure: g3_entry_check (origin step s2b_enter): 2026-09-14 Reg: no status reported
```

The `run` record carries `origin_step: s2b_enter`; the guardrail record carries
`checked_output` (the file it inspected) and `reason`; the step record carries
the model, tokens, cost and the path of the full transcript
(`s2b_enter.stream.jsonl`). The fix was a prompt change in `workflow/prompts.py`
(click SSO once, report LOGIN REQUIRED only if credentials are asked for).

## 2. Fault injection: `--inject-fault s1_activity`

See below (appended after the run).
