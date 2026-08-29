#!/usr/bin/env python3
"""Generic prompt-eval runner for any skill in this repo.

Tests whether Claude, given a skill, responds correctly to a prompt — not
whether the skill's underlying script works (that's what each skill's own
unit tests are for).

Loads `.claude/skills/<skill>/evals/cases.json`, which is the *native*
pydantic_evals.Dataset file format (see Dataset.to_file/from_file) — no
custom schema, no translation step. Each case runs as a real headless
Claude Code turn (`claude -p`) and reports straight to Logfire.

Usage:
    python3 evals/run_skill_eval.py weekly-activity
    python3 evals/run_skill_eval.py weekly-activity --repeat 3

Real API cost is incurred per case per repeat (a trivial no-tool call
measured ~$0.19 on Opus; the default model here is Haiku, which costs much
less) — the estimate is printed before running, but nothing is gated behind
a flag.

Tool calls the nested Claude session makes are parsed out of the
--output-format stream-json output and re-emitted as local logfire spans
inside the task function, because pydantic_evals' HasMatchingSpan (and other
span-based evaluators) only see spans emitted in-process during the task
call — a subprocess's own spans, exported straight to Logfire, aren't
visible to the parent's local span tree. This replay is the only non-declar-
ative code in the whole runner.

Judging (rubric-based assertions) uses `ClaudeCLIJudge`, a small custom
evaluator that shells out to `claude -p` the same way the task does, instead
of pydantic_evals' built-in LLMJudge — LLMJudge needs a pydantic_ai model
client with a real provider API key (OPENAI_API_KEY/ANTHROPIC_API_KEY),
which this environment doesn't have. The CLI is already authenticated, so
ClaudeCLIJudge needs no separate key at all.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import logfire
from dotenv import load_dotenv
from pydantic_evals import Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from pydantic_evals.evaluators.evaluator import EvaluationReason

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fills in LOGFIRE_TOKEN etc. from .env. Existing env vars always win --
# load_dotenv() doesn't override what's already set.
load_dotenv(REPO_ROOT / ".env")

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Where eval results get pushed -- used only to print a direct link to the
# run afterward, not for sending (that's driven by LOGFIRE_TOKEN itself).
LOGFIRE_BASE_URL = "https://logfire-us.pydantic.dev"
LOGFIRE_ORG = "tonan-salas-cruz"
LOGFIRE_PROJECT = "tool-evals"

# Floor per case, based on a measured trivial no-tool-use claude -p call on
# Opus. Haiku (the default here) costs meaningfully less; tool-using prompts
# cost more regardless of model — this is a heads-up, not a quote.
EST_COST_PER_CASE_USD = 0.19


def get_git_branch() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or "unknown-branch"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown-branch"


def logfire_trace_link(trace_id: str, since: datetime, until: datetime) -> str:
    """A direct Logfire live-view link filtered to this run's trace, so you
    don't have to navigate/refresh the Evals UI by hand to find it."""
    query = urllib.parse.quote(f"trace_id='{trace_id}'")
    since_s = urllib.parse.quote(since.isoformat())
    until_s = urllib.parse.quote(until.isoformat())
    return f"{LOGFIRE_BASE_URL}/{LOGFIRE_ORG}/{LOGFIRE_PROJECT}/?q={query}&since={since_s}&until={until_s}"


def _span_name(tool_name: str, tool_input: dict) -> str:
    # Summarize into the span name (not just attributes) so substring
    # queries like HasMatchingSpan({"name_contains": "..."}) can match
    # directly against what the tool actually did, e.g. the Bash command.
    summary = tool_input.get("command") or tool_input.get("description") or json.dumps(tool_input)
    # Strip braces so logfire doesn't try to treat the name as a template string.
    summary = summary.replace("{", "(").replace("}", ")")
    return f"{tool_name}({summary})"[:300]


def run_claude_headless(prompt: str, model: str) -> tuple[str, list[dict]]:
    """Run one headless Claude turn. Returns (final_text, tool_calls)."""
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed (exit {proc.returncode}): {proc.stderr[-2000:]}")

    final_text = ""
    tool_calls: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tool_calls.append({"name": block.get("name", "tool"), "input": block.get("input", {})})
        elif event.get("type") == "result":
            final_text = event.get("result", final_text)

    return final_text, tool_calls


def make_task(model: str):
    def task(inputs: str) -> str:
        final_text, tool_calls = run_claude_headless(inputs, model)
        for call in tool_calls:
            with logfire.span(_span_name(call["name"], call["input"])):
                pass
        return final_text

    return task


_JUDGE_VERDICT_RE = re.compile(r"^\s*(PASS|FAIL)\b", re.IGNORECASE)


@dataclass
class ClaudeCLIJudge(Evaluator[str, str]):
    """Rubric-based judging via the authenticated `claude` CLI — no API key needed.

    A drop-in alternative to pydantic_evals' built-in LLMJudge, which requires
    a pydantic_ai model client backed by a real provider API key. This shells
    out the same way the task itself does, so it reuses the CLI's existing
    auth instead of asking for a separate credential.
    """

    rubric: str = ""
    model: str = DEFAULT_MODEL

    async def evaluate(self, ctx: EvaluatorContext[str, str]) -> EvaluationReason:
        judge_prompt = (
            "You are grading whether a response satisfies a rubric. "
            "Do not use any tools -- just reply directly.\n\n"
            f"Rubric: {self.rubric}\n\n"
            f"Response to grade:\n{ctx.output}\n\n"
            "Reply with exactly one line starting with PASS or FAIL, "
            "followed by a one-sentence reason."
        )
        proc = subprocess.run(
            ["claude", "-p", judge_prompt, "--model", self.model, "--output-format", "json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            return EvaluationReason(value=False, reason=f"judge call failed (exit {proc.returncode}): {proc.stderr[-500:]}")

        try:
            result_text = json.loads(proc.stdout).get("result", "")
        except json.JSONDecodeError:
            return EvaluationReason(value=False, reason=f"judge returned non-JSON output: {proc.stdout[:300]}")

        match = _JUDGE_VERDICT_RE.match(result_text)
        if not match:
            return EvaluationReason(value=False, reason=f"judge reply didn't start with PASS/FAIL: {result_text[:300]}")

        return EvaluationReason(value=match.group(1).upper() == "PASS", reason=result_text.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("skill", help="Skill directory name under .claude/skills/")
    parser.add_argument("--repeat", type=int, default=1, help="Times to repeat each case (default 1)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model for both the task and the judge (default {DEFAULT_MODEL})")
    args = parser.parse_args()

    cases_path = REPO_ROOT / ".claude" / "skills" / args.skill / "evals" / "cases.json"
    if not cases_path.exists():
        sys.exit(f"No eval cases found at {cases_path}")

    dataset = Dataset.from_file(cases_path, custom_evaluator_types=[ClaudeCLIJudge])
    for case in dataset.cases:
        for evaluator in case.evaluators:
            if isinstance(evaluator, ClaudeCLIJudge):
                evaluator.model = args.model

    n_cases = len(dataset.cases)
    est_total = n_cases * args.repeat * EST_COST_PER_CASE_USD
    print(
        f"Running {n_cases} case(s) x {args.repeat} repeat(s) for '{args.skill}' on {args.model} "
        f"-- estimated cost: ~${est_total:.2f} floor (prompts with tool use cost more)"
    )

    if os.environ.get("LOGFIRE_TOKEN"):
        print("LOGFIRE_TOKEN is set -- results will be sent to Logfire.")
    else:
        print(
            "WARNING: LOGFIRE_TOKEN is not set -- results will NOT be sent to Logfire, "
            "only printed locally below. Add it to .env at the repo root to fix this."
        )

    logfire.configure(send_to_logfire="if-token-present", service_name=f"{args.skill}-eval")

    branch = get_git_branch()
    run_started = datetime.now(timezone.utc)
    run_name = f"{branch}_{run_started.strftime('%Y%m%d-%H%M%S')}"
    report = dataset.evaluate_sync(make_task(args.model), name=run_name, repeat=args.repeat)
    run_ended = datetime.now(timezone.utc)
    report.print(include_input=False, include_output=False)

    if os.environ.get("LOGFIRE_TOKEN") and report.trace_id:
        print(f"\nView this run in Logfire: {logfire_trace_link(report.trace_id, run_started, run_ended)}")


if __name__ == "__main__":
    main()
