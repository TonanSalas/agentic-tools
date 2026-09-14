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

## 2. A second real failure, then the fix: run `20260914-043509-596c`

The next run failed at the same step for a different reason the audit made
visible. The entry agent logged in, then got stuck on Workday's off-screen
"Menu" side-dialog and finally navigated to the deep-link task URL — which drops
onto a fresh Microsoft sign-in and looks like a login failure. It even diagnosed
this in its own transcript. `g3_entry_check` caught the empty result and stopped
the run before submit and Teams.

```
# 20260914-043509-596c

2026-09-14T04:35:24.445497+00:00  step      s1_activity            success          model=claude-sonnet-5 in=4 cache_read=95771 cache_write=17871 out=480 cost=$0.0954
2026-09-14T04:35:24.454420+00:00  guardrail g1_activity_check      passed           reason='2 days, 0 refs, TEC report well-formed'
2026-09-14T04:35:35.361938+00:00  step      g1_adversarial         success          model=claude-haiku-4-5-20251001 in=9 cache_read=31211 cache_write=9971 out=388 cost=$0.0250
2026-09-14T04:35:35.362432+00:00  guardrail g1_adversarial         passed           reason='reviewer found no unsupported claims'
2026-09-14T04:36:01.305402+00:00  step      s2a_plan               success          model=claude-sonnet-5 in=12 cache_read=354192 cache_write=23817 out=1317 cost=$0.1793
2026-09-14T04:36:01.323522+00:00  guardrail g2_plan_check          passed           reason='2 entries over 2 days within limits and grounded'
2026-09-14T04:41:17.020716+00:00  step      s2b_enter              success          model=claude-sonnet-5 in=100 cache_read=4218148 cache_write=60851 out=10740 cost=$1.1946
2026-09-14T04:41:17.035433+00:00  guardrail g3_entry_check         failed           reason='entry step reported an error: LOGIN REQUIRED'
2026-09-14T04:41:17.043669+00:00  run       20260914-043509-596c   failed          

First failure: g3_entry_check (origin step s2b_enter): entry step reported an error: LOGIN REQUIRED
```

The fix hardened both `workday-timelogger`'s SKILL.md and the harness `s2b`
prompt: never deep-link, and treat the off-screen Menu dialog as inert. The next
run (`20260914-044403-fa88`) entered both days successfully and passed
`g3_entry_check`.

## 3. The improvement this produced

The `success-report.md` trend is `0% → 0% → 33% → 50% → 60% → 66.7%`: two real
defects in the live-browser entry step surfaced by the audit and traced to
`s2b_enter`, both fixed, then four consecutive successes (one with a real
Workday entry, three dry-run). This is the audit trail doing its job — every
failure named its origin step, which is what made each fix targeted.

## Fault injection (guardrail demonstration)

`python3 workflow/run_weekly_log.py --test --inject-fault s1_activity` appends a
ticket that the gathered GitHub data never contained to step 1's output, exactly
what a hallucinating step would do. `g1_activity_check` rejects it with
`N ref(s) not in the gathered data (fabrication?): agentic-org#99999` and the run
ends `failed` with `origin_step: s1_activity` before any time is entered. This
path is covered by `workflow/tests/test_run_weekly_log.py::test_inject_fault_s1_is_caught_by_g1`.
