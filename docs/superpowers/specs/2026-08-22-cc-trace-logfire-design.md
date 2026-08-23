# Claude Code session tracing to Logfire, plus a deterministic performance eval

**Status:** design
**Owner:** Tonan Salas

## Summary

Instrument every Claude Code session in this repo — user turns, tool calls (including
`Skill` and `Task`/subagent invocations), and subagent transcripts — as OTel spans sent
to Pydantic Logfire, using Claude Code's own hooks. Then add a small deterministic eval
that queries those traces and scores sessions on two axes: **reliability** (tool errors,
dropped tracing jobs, latency outliers) and **skill-usage correctness** (a per-skill
invariant table, e.g. no duplicate destructive calls, no submit-without-confirmation).

This is architecturally adapted from the `trace-claude-code` Claude Code plugin
(`judgeval-claude-plugin`, installed at
`~/.claude/plugins/cache/judgeval-claude-plugin/trace-claude-code/1.0.0/`), which does
the same job for Judgment Labs. The plumbing (hook-is-dumb / worker-is-smart /
filesystem-queue, locking, recovery chain) is adapted closely; the upload target and
attribute naming are swapped for Logfire's OTLP endpoint, and the transcript-parsing /
span-building step — the one part of the reference that's genuinely fiddly (streamed-chunk
usage dedup, tool_use/tool_result pairing) — is reimplemented in Python instead of bash+jq,
so it can carry pytest coverage.

## Vocabulary

- **session_id** — Claude Code's own session id (hook stdin `session_id`, or
  `basename(transcript_path, .jsonl)` as fallback). Stable across a whole conversation.
- **turn** — one `UserPromptSubmit` → `Stop` cycle. Becomes one trace, containing a root
  span, a Task span, and child spans for each LLM call and tool call in that turn.
- **job** — a small JSON file in the filesystem queue describing one unit of deferred
  work (`turn_start`, `finalize`, `subagent`, `span`, ...). Written by a hook, consumed
  by the worker.
- **worker** — the single detached background process (`nohup ... & disown`, PID-file
  mutex) that drains the queue: parses transcript slices, builds OTLP spans, POSTs to
  Logfire, retries on failure.

## Goals / non-goals

**Goals**
- Every session's turns, tool calls, and subagent activity land in Logfire as queryable
  spans, with no dependency on stdout (robust to piping/redirection inside tool calls).
- Hooks never add latency or can never fail/block a Claude Code session — this is the
  hard safety requirement carried over from the reference design.
- A deterministic eval script that scores recent sessions on reliability and skill-usage
  correctness, runnable on demand (`python3 evals/run_eval.py`).
- Reuse `LOGFIRE_TOKEN` already present in this repo's `.env`.

**Non-goals**
- LLM-judged quality scoring (explicitly out of scope per requirements — deterministic
  checks only for v1).
- Live/streaming visibility mid-turn — spans land after each turn's `Stop` (or session
  end), not in real time within a turn.
- A generic multi-project setup wizard like the reference's `setup.sh` walks several
  providers — this is single-repo, single-backend (Logfire only).

## Design

### Where it lives

```
.claude/hooks/cc-trace/
  hooks/
    session_start.sh
    user_prompt_submit.sh
    stop_hook.sh
    session_end.sh
    subagent_start.sh
    subagent_stop.sh
  lib/
    common.sh              # state/lock/queue helpers, adapted from reference common.sh
    parse_turn.py           # transcript slice -> span list (the ported "smart" step)
    tests/
      test_parse_turn.py
  worker.sh                 # queue drain loop, calls parse_turn.py, POSTs to Logfire
  setup.sh                  # writes hooks + env into .claude/settings.local.json
evals/
  cc_trace/
    logfire_client.py       # read-only Logfire Query API client (httpx GET /v1/query)
    evaluators.py           # reliability + skill-usage-correctness checks
    run_eval.py             # CLI entry point
    tests/
      test_evaluators.py
```

State lives under `~/.claude/state/cc_trace_*` (see below) — outside the repo, same as
the reference, since it's per-machine coordination state, not project data.

### Hook registration

`setup.sh` writes these into `.claude/settings.local.json` under `"hooks"` (merging with
whatever's already there, same `jq`-merge approach as the reference), each with an
explicit timeout as the hard backstop:

| Event | Script | Timeout |
|---|---|---|
| `SessionStart` | `session_start.sh` | 10s |
| `UserPromptSubmit` | `user_prompt_submit.sh` | 10s |
| `Stop` | `stop_hook.sh` | 30s |
| `SessionEnd` | `session_end.sh` | 120s |
| `SubagentStart` (matcher `*`) | `subagent_start.sh` | 10s |
| `SubagentStop` | `subagent_stop.sh` | 30s |

No `PreToolUse`/`PostToolUse` — tool calls (including `Skill` and `Task` invocations)
are reconstructed by parsing each turn's transcript slice, not captured live. This
matches the reference and keeps the hook surface minimal.

### State files (bash, adapted from reference `common.sh`)

Same mechanism as the reference, renamed off `judgeval_*`:

| Path | Purpose |
|---|---|
| `~/.claude/state/cc_trace_state.json` | session/subagent coordination state (mkdir-lock + atomic tmp-then-`mv` on every write) |
| `~/.claude/state/cc_trace_lock.d/` | mkdir-based mutex for state read-modify-write, force-broken if >30s stale |
| `~/.claude/state/cc_trace_queue/pending/*.json` | queued jobs, hooks write here |
| `~/.claude/state/cc_trace_queue/processing/*.json` | jobs the worker has claimed; leftover files here on worker startup (crash residue) are moved back to `pending/` |
| `~/.claude/state/cc_trace_queue/worker.pid` | noclobber singleton lock for the worker |
| `~/.claude/state/cc_trace_blobs/<ref>.json` | large turn input/output payloads, referenced by id rather than inlined into `state.json` |
| `~/.claude/state/cc_trace_hook.log` | append-only hook/worker log |

Session state carries the same fields the reference does: `transcript_path`,
`transcript_offset` (incremental line-count cache), `turn_count`, and the active-turn
fields (`active_trace_id`, `active_root_span_id`, `active_task_span_id`,
`active_prompt`, `active_transcript_offset`) that let `Stop` (or the `SessionEnd`
fallback) know what to finalize. `subagent:<agent_id>` entries carry the durable
parent-trace mapping, written synchronously at `SubagentStart` — before any race with
`SubagentStop` — exactly as the reference does it.

### Queue + worker (bash, adapted from reference `worker.sh`)

Unchanged from the reference in spirit:
- `enqueue_payload()` writes a job to `pending/<nanos>-<pid>-<random>.json` (temp file +
  atomic `mv`), then `ensure_worker_running()` — `nohup bash worker.sh </dev/null
  >/dev/null 2>&1 & disown`, fully detached so a hook's exit/timeout never touches it.
- `worker.sh` claims the PID lock (`set -C` noclobber), polls `pending/` oldest-first
  (nanosecond-prefixed names), `mv`s a job into `processing/` before dispatching it by
  `type`, retries `span`/`subagent`/`finalize` job types up to 5 attempts with linear
  backoff (2s/4s/6s/8s) under a **new** filename each retry (so one stuck job doesn't
  block the queue head), and self-exits after 60s idle (respawned on next enqueue).
- Job types: `turn_start`, `finalize`, `subagent_start`, `subagent`, `span` — same set
  as the reference minus `notification_attach`/`relay_attach` (the reference's
  background-task-notification handling; deferred — see Open questions).

**What changes**: wherever the reference's `worker.sh`/`turn_trace_common.sh` calls into
jq to parse a transcript slice and build spans, this version instead shells out to
`lib/parse_turn.py` with the transcript path and line-range slice, gets back a JSON list
of ready-to-upload span objects (already OTLP-shaped), and the bash worker just POSTs
them. Same seam for `subagent_stop.sh`'s processing mode — it calls the *same*
`parse_turn.py` (parameterized by transcript path, since a subagent has its own
transcript file), rather than the reference's duplicated inline bash parser. This is a
genuine improvement over the reference, not just a language swap: one parser, one set of
tests, used by both the normal-turn and subagent code paths.

### `parse_turn.py` (Python — the ported "smart" step)

Input: transcript path, start/end line offsets (a turn's slice), trace/span ids, turn
metadata (index, prompt). Output: a JSON list of span dicts (name, parent id, start/end
time, attributes), printed to stdout for the bash worker to POST.

Responsibilities (ported from the reference's `turn_trace_common.sh` /
`subagent_stop.sh`'s inline parser):
- Stream the transcript slice, replaying Claude Code's JSONL record types
  (`assistant`, `user` with `tool_result`, plain `user` text) into: accumulated
  `tool_use` blocks keyed by `tool_use_id`, concatenated assistant text, and a
  `requestId → final usage/timestamp` map (precomputed once per slice) so a streamed
  LLM call's chunks collapse into exactly one span with corrected token counts — this is
  the trickiest bit of the reference and the main reason this step is Python: it gets
  unit tests with synthetic transcript fixtures instead of eyeballed jq behavior.
- Emit one LLM span per deduped `requestId`, one tool span per paired
  `tool_use`/`tool_result` (using the call's start time and the result's timestamp as
  span bounds), the turn's Task span (parent = root), and the root span — same
  structure as the reference.
- Malformed lines are dropped, not fatal (mirrors the reference's defensive parsing) —
  one bad JSONL line must never abort the whole turn's spans.

### Upload (bash, simpler than the reference)

No project-resolve/create step: `LOGFIRE_TOKEN` is itself project-scoped, so
`worker.sh` POSTs an OTLP `resourceSpans` envelope directly to
`https://logfire-us.pydantic.dev/v1/traces` (overridable via `LOGFIRE_BASE_URL`, same
env var name `agentic-org`'s collector uses) with `Authorization: Bearer
$LOGFIRE_TOKEN`, `curl --max-time 60 --connect-timeout 5`, success = 2xx. One span (or a
small batch) per request, same as the reference's per-span POST pattern.

### Attributes

Plain, non-provider-specific naming (no `judgment.*` prefix):

- `session_id`, `turn_index` on every span.
- Root/Task spans: `input` / `output` (JSON-encoded conversation envelope, same shape
  idea as the reference's `judgment.input`/`judgment.output`), `llm_call_count`,
  `tool_count`, `workspace`.
- Tool spans: `tool_name`, `tool_input` (JSON), `tool_output` (JSON, truncated),
  `is_error`.
- Subagent container spans: `agent_type`, `agent_id`, nested under the parent turn's
  Task span via the durable `subagent:<agent_id>` mapping, same as the reference.

### Recovery chain

Identical to the reference: if `Stop` is killed before finalizing (hits its own 30s
timeout), the next `UserPromptSubmit` detects the still-set `active_trace_id` and
synthesizes the missed `finalize` job before starting the new turn. `SessionEnd` is the
last-resort net — if `active_*` state is still set, it finalizes directly; either way it
blocks up to 90s polling the queue for emptiness (so the background worker gets a bounded
window to flush) before pruning the session's state entries and blob files.

### Safety guarantees (carried over unchanged)

- Every hook: `set -e; trap 'exit 0' ERR` — any internal failure becomes a clean exit 0.
- `tracing_enabled()` gate at the top of every hook: if `TRACE_TO_LOGFIRE` isn't
  `"true"`, or `jq`/`curl`/`python3` are missing, or `LOGFIRE_TOKEN` is unset, the hook
  logs and exits 0 without doing anything.
- **No hook performs network I/O.** Only `worker.sh` does, and it's fully detached, so a
  slow/dead Logfire endpoint can never add latency to a Claude Code session.
- Invalid hook stdin JSON is checked immediately (`jq -e '.' >/dev/null 2>&1 || exit 0`).
- State-file corruption resilience: reads validate the file is a JSON object before
  trusting it, falling back to `{}` with a logged warning; writes refuse to persist
  anything that isn't valid JSON; all writes are atomic (temp file + `mv -f`).

## Eval component

Two evaluator families, run over Logfire trace data via a read-only Query API client
(`evals/cc_trace/logfire_client.py`, same `httpx GET /v1/query` pattern as
`agentic-org/tools/portal_recon/logfire_client.py`):

**Reliability**
- Tool error rate per session/skill (`is_error` attribute).
- Dropped tracing jobs — worker logs a warning span/event when a job hits the 5-attempt
  cap; this surfaces the tracing pipeline's own health, not just tool failures.
- Latency outliers per tool (span duration vs. that tool's historical p95).

**Skill-usage correctness**
- A small, explicit per-skill invariant table (extensible — starts with generic checks
  that don't need per-skill special-casing):
  - No duplicate tool call with identical name+input within one skill's span (wasted
    work / retry-without-backoff smell).
  - No unhandled tool error inside a skill's span (an error span with no subsequent
    successful retry of the same tool before the skill's span closes).
  - For skills whose SKILL.md documents a confirm-before-submit step (verified today:
    `eip-points`, `engage-cv-import`, `workday-timelogger` — see project memory
    `feedback_workday_flow.md`), a plain-text user turn or an `AskUserQuestion` tool
    call appears in the turn before the terminal submit-type tool call.

Each evaluator returns pass/fail + a reason string per session, printed as a report by
`evals/cc_trace/run_eval.py --since <duration>`.

## Config / env vars

Written into `.claude/settings.local.json` under `"env"` by `setup.sh` (merged with any
existing env):

| Var | Required | Default | Purpose |
|---|---|---|---|
| `TRACE_TO_LOGFIRE` | yes | — | must be `"true"` to enable any tracing |
| `LOGFIRE_TOKEN` | yes | — | already present in `.env`; `setup.sh` picks it up as the pre-filled default the way the reference scans for `JUDGMENT_API_KEY` |
| `CC_TRACE_DEBUG` | no | `false` | enables debug-level hook log lines |

`setup.sh` requires `jq`, `curl`, `python3` (checked up front), validates all hook
scripts exist, and does **no** synchronous network smoke-test call (unlike the
reference's project-resolve check) since there's no project-resolve step to test.

## Testing

- `lib/parse_turn.py`: pytest, mocked transcript JSONL fixtures — the dedup logic
  (streamed-chunk usage correction, tool_use/tool_result pairing, malformed-line
  skipping) is exactly what the Python port is for, so it needs to be verified, not
  eyeballed.
- `evals/cc_trace/evaluators.py`: pytest, synthetic span/session fixtures (no network) —
  same shape as the pattern this repo already has for `weekly-activity`.
- Hooks and `worker.sh` (bash): no unit tests — their only job is "never break Claude
  Code," verified by a manual smoke test (valid/invalid stdin → always exit 0; a real
  session produces spans visible in Logfire) rather than an automated bash test harness,
  since there's no existing bash test infra in this repo to build on and the safety
  property (always exit 0, gated gracefully) is simple enough to eyeball in the adapted
  code.

## Open questions

- The reference's `notification_attach`/`relay_attach` job types (background/async
  subagent completions delivered via a synthetic `<task-notification>` user prompt) are
  out of scope for v1 — none of this repo's current skills spawn long-running background
  subagents, so this can be added later if that changes.
- `migrate_state.sh` (the reference's self-healing pass for an oversized legacy state
  file) is not ported for v1 — the coordination state file starts empty and the blob
  side-channel already keeps its steady-state size bounded; add this later if
  `cc_trace_state.json` is ever observed to grow unexpectedly.
