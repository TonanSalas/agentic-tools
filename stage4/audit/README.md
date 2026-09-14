# Audit trail

Every harness run writes `workflow/runs/<run_id>/audit.jsonl`; the evidence
runs' logs are copied here. One JSON record per line, in execution order.

## Record fields

Common to every record: `run_id`, `ts` (UTC ISO 8601), `kind`, `id`, `outcome`.

| `kind` | `id` | `outcome` values | extra fields |
|---|---|---|---|
| `step` | `s1_activity`, `g1_adversarial`, `s2a_plan`, `s2b_enter`, `s2c_submit`, `s3_send` | `success`, `failed`, `skipped` | `model` (comma-joined if a step used several), `model_usage` (per-model input/output/cache tokens and `costUSD`), `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `cost_usd`, `duration_ms`, `num_turns`, `session_id`, `tool_calls`, `blocked_calls`, `raw_path` (full `stream-json` transcript of the turn), `error` |
| `guardrail` | `g1_activity_check`, `g2_plan_check`, `g3_entry_check`, `g4_message_check`, `g1_adversarial`, `hook_p1`, `hook_p2` | `passed`, `failed` | `passed`, `reason`, `checked_output` (the file inspected), `origin_step` (the step that produced it) |
| `punchout` | `p1_submit_timesheet`, `p2_send_to_others` | `approved`, `awaiting_human`, `rejected_by_human`, `not_required`, `skipped` | `sentinel_path`, `decision`, `decided_by` |
| `fault` | `inject_s1_activity` | `injected` | `reason` — only present when `--inject-fault` was used |
| `run` | the run id | `success`, `failed`, `awaiting_human`, `rejected_by_human` | `origin_step`, `reason`, `total_cost_usd`, `mode`, `start`, `end`, `hours`, `teams_target`, flags |

Token and cost figures come straight from Claude Code's `result` event for
each headless turn (`usage`, `modelUsage`, `total_cost_usd`), so "which model,
how many input and output tokens, what did this step cost" is answered per
step without estimation. `g1_adversarial` is recorded as a step *and* as a
guardrail: the step record carries its cost, the guardrail record its verdict.

## Tracing a failure to its origin step

`python3 workflow/report.py --run <run_id>` prints the records in order and
names the first record whose outcome is `failed`, together with its
`origin_step`. See `trace-example.md` for a real run in which step 1's output
was tampered with (`--inject-fault s1_activity`) and `g1_activity_check`
stopped the workflow before step 2 ran.
