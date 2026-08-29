# Generic skill eval runner

Date: 2026-08-23

## Problem

Two prior attempts at evaluating `weekly-activity` were both wrong in different ways:

1. `evals/evals.json` + a skill-creator-style graded replay pushed to Logfire — worked, but invented its own JSON schema (`evals.json` / `eval_metadata.json` / `grading.json`) that Logfire never sees, requiring a translation script to bridge it.
2. `evals/run_evals.py` — repeatedly invoked `gather_activity.py` directly to check determinism. This tests the *script*, which already has its own pytest suite (cheaper, faster, no LLM calls). An eval's job is to test whether **Claude, given a skill, responds correctly to a prompt** — not to re-test code that unit tests already cover.

Both were also skill-specific one-offs, with no path to reuse for any other skill in the repo.

## Design

One generic runner, reusable across every skill; case data authored directly in `pydantic_evals`' own native serialization format — no invented schema, no translation step.

### File layout

```
evals/run_skill_eval.py                      # repo root — shared, generic, not a skill
.claude/skills/<skill>/evals/cases.json       # per-skill — native pydantic_evals.Dataset format
```

`run_skill_eval.py` lives at the repo root, not under `.claude/skills/`, because it isn't scoped to one skill and a directory there without a `SKILL.md` would break Claude Code's skill-scanning convention. `cases.json` stays inside each skill's own folder — consistent with the existing precedent of `weekly-activity/tests/` living alongside the skill it tests.

### Case format

`cases.json` is exactly what `pydantic_evals.Dataset.to_file()` produces and `Dataset.from_file()` loads — verified by round-tripping a sample dataset. No custom parsing exists in the runner; evaluators are pydantic-evals' own built-in classes (`HasMatchingSpan`, `Contains`, `Equals`, `IsInstance`, `MaxDuration`, `LLMJudge`), reached for in that order before any custom `Evaluator` subclass.

### Invocation

The task function shells out to `claude -p "<prompt>" --output-format stream-json` — a real headless Claude Code turn, run synchronously from the `pydantic_evals` task callable. This is what makes the eval test actual prompt-driven behavior instead of a canned replay.

### The span-replay bridge

`HasMatchingSpan` (and other span-based evaluators) only see spans emitted **in-process** during the task call — pydantic-evals wires up a local span tree via `logfire.configure()`, and a subprocess's own spans (exported straight to Logfire) aren't visible to it. The task function parses the `tool_use` blocks out of the `stream-json` stream and re-emits each as a local `logfire.span()`, named to include the tool's actual input (e.g. the Bash command) so `name_contains` queries can match against it directly. This is the only non-declarative code in the design — everything else is data.

### Logfire mapping

One dataset per skill (dataset name = skill name), experiment name = `<branch>_<UTC timestamp>` — lets results be compared before/after a change on a branch directly in Logfire's Experiments tab, and keeps every run distinguishable (a static branch-only name meant repeat runs on the same branch all shared one experiment name, making new runs look like nothing had landed).

### Cost

No hard guardrail. The runner prints an estimated cost (`cases × repeat × ~$0.19` floor, measured from a trivial no-tool-use call) before running, then proceeds — the user already chooses one skill deliberately per run (no `--all` sweep exists).

### Explicitly out of scope

- Bulk/sweep mode across all skills in one invocation (Q2: rejected — keeps cost and scope deliberate per run).
- A forced confirmation flag above some cost threshold (Q4: rejected — printed estimate is enough).
- Re-testing `gather_activity.py`'s own determinism — that's `weekly-activity/tests/`'s job, not this eval's.

## Verification

Ran for real against `weekly-activity` (3 cases, `main` branch, ~$0.57 estimated): the nested `claude -p` session correctly invoked the `weekly-activity` skill and `Bash`'d `gather_activity.py` with the right flags in all 3 cases. `HasMatchingSpan` and `Contains` evaluators matched correctly via the span-replay bridge — this is real evidence the bridge works, not just that it loads.

**Known gap:** `LLMJudge` assertions failed in this run — `OpenAIError: api_key client option must be set`. This environment has no `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` (only `ANTHROPIC_BASE_URL`, Claude Code's own internal proxy auth, which `pydantic_ai`'s model clients can't use directly). Judge-based assertions need a real provider key added to `.claude/settings.local.json`'s `env` block before they'll run — not addressed here since it means adding credentials, which needs the user's decision.
