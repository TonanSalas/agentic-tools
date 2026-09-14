# weekly-log end-to-end success report

Generated: 2026-09-14T04:58:49+00:00

**End-to-end success rate: 66.7%** (4 of 6 runs that ran to a workflow outcome; 6 runs total, 0 stopped by a human rejection at a punch-out, 0 still awaiting a human).

Rate = success / (success + failed). A human rejection at a punch-out is a decision, not a workflow failure, and is listed but not counted against the workflow.

## Per run

| # | Run | Mode | Outcome | Origin step (if failed) | Cost USD | Tokens |
|---|---|---|---|---|---|---|
| 1 | 20260914-035313-37ad | test | failed | s2b_enter | 0.4562 | 3549 |
| 2 | 20260914-043509-596c | test | failed | s2b_enter | 1.4944 | 13050 |
| 3 | 20260914-044403-fa88 | test | success |  | 2.0872 | 16854 |
| 4 | 20260914-045116-f85a | test | success |  | 0.6350 | 5216 |
| 5 | 20260914-045327-676e | test | success |  | 0.5541 | 2506 |
| 6 | 20260914-045557-0c41 | test | success |  | 0.5185 | 4199 |

## Trend (cumulative success rate after each decided run)

0.0% → 0.0% → 33.3% → 50.0% → 60.0% → 66.7%

## Per step / guardrail pass rate

| Id | Pass | Fail |
|---|---|---|
| g1_activity_check | 6 | 0 |
| g1_adversarial | 12 | 0 |
| g2_plan_check | 6 | 0 |
| g3_entry_check | 1 | 2 |
| g4_message_check | 4 | 0 |
| s1_activity | 6 | 0 |
| s2a_plan | 6 | 0 |
| s2b_enter | 3 | 0 |
| s3_send | 4 | 0 |
