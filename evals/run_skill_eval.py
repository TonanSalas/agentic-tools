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

Real API cost is incurred per case per repeat, for the task turns only —
grading is free. The estimate is printed before running.

**Grading is deterministic wherever the expectation can be stated literally.**
`ScriptExecuted`, `DayCoverage` and `GroundedIdentifiers` take their
expectations as data in `cases.json` and are pure matchers over that data —
none of them derives what it expects at grading time.

That property was arrived at the hard way and is recorded in
`ITERATION_LOG.md`:

- An earlier grounding check asked an LLM judge whether ticket numbers looked
  real. It failed a correct response with "presents highly specific PR
  numbers... I cannot verify are real" — penalising accuracy for looking
  unverifiable.
- Its replacement fetched the script's own payload at grading time and
  compared against that. Deterministic, but circular: it asked "does the
  response match what the script says now", not "does the response match the
  truth". A regressed script would have taken the eval down with it and still
  scored 100%.

`ClaudeCLIJudge` is the one rubric-graded dimension, covering the expectation
that cannot be written as a literal: the shape and prose of the TEC status
report the skill emits under a top-level `summary` key. It follows the same
contract as the other three — the expectation lives in `cases.json`, per case,
and the evaluator only applies it. Its rubric is written per case because the
cases differ in substance, not just in parameters: one week's Planned
Activities are legitimately empty (everything merged), the next week's must
name the PR still in review, and the future week must name no work at all.

It is never asked whether anything is *real*: that is precisely what sank the
first grounding judge, and it stays `GroundedIdentifiers`' job. Every rubric
below grades only what is decidable from the response text itself.

Tool calls the nested Claude session makes are parsed out of the
--output-format stream-json output and re-emitted as local logfire spans
inside the task function, because span-based tooling only sees spans emitted
in-process during the task call — a subprocess's own spans, exported straight
to Logfire, aren't visible to the parent's local span tree. Only calls whose
`tool_result` came back without an error are replayed, so a *blocked* or
*failed* call can't be mistaken for a call that ran.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import logfire
from dotenv import load_dotenv
from pydantic_evals import Dataset, set_eval_attribute
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


# --------------------------------------------------------------------------
# Task
# --------------------------------------------------------------------------

def logfire_trace_link(trace_id: str, since: datetime, until: datetime) -> str:
    """A direct Logfire live-view link filtered to this run's trace, so you
    don't have to navigate/refresh the Evals UI by hand to find it."""
    query = urllib.parse.quote(f"trace_id='{trace_id}'")
    since_s = urllib.parse.quote(since.isoformat())
    until_s = urllib.parse.quote(until.isoformat())
    return f"{LOGFIRE_BASE_URL}/{LOGFIRE_ORG}/{LOGFIRE_PROJECT}/?q={query}&since={since_s}&until={until_s}"


def _span_name(tool_name: str, tool_input: dict) -> str:
    # Summarize into the span name (not just attributes) so substring
    # queries can match directly against what the tool actually did.
    summary = tool_input.get("command") or tool_input.get("description") or json.dumps(tool_input)
    # Strip braces so logfire doesn't try to treat the name as a template string.
    summary = summary.replace("{", "(").replace("}", ")")
    return f"{tool_name}({summary})"[:300]


def run_claude_headless(prompt: str, model: str) -> tuple[str, list[dict]]:
    """Run one headless Claude turn.

    Returns (final_text, successful_tool_calls). A call counts as successful
    only if its `tool_result` came back without `is_error` -- a call the
    session merely *attempted* (blocked by permissions, or failed outright)
    is not evidence that anything ran.
    """
    proc = subprocess.run(
        # No --allowedTools: the tools the skill needs are pre-approved in the
        # project's .claude/settings.json, so the nested session runs under the
        # same permission config as real usage. With neither, it hits an
        # interactive permission prompt it can't answer in headless mode and
        # returns "I need approval to run..." -- grading a refusal, not a skill.
        ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed (exit {proc.returncode}): {proc.stderr[-2000:]}")

    final_text = ""
    attempted: dict[str, dict] = {}
    completed: list[str] = []

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
                    attempted[block.get("id", "")] = {
                        "name": block.get("name", "tool"),
                        "input": block.get("input", {}),
                    }
        elif event.get("type") == "user":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_result" and not block.get("is_error"):
                    completed.append(block.get("tool_use_id", ""))
        elif event.get("type") == "result":
            final_text = event.get("result", final_text)

    succeeded = [attempted[i] for i in completed if i in attempted]
    return final_text, succeeded


def make_task(model: str):
    def task(inputs: str) -> str:
        final_text, tool_calls = run_claude_headless(inputs, model)
        for call in tool_calls:
            with logfire.span(_span_name(call["name"], call["input"])):
                pass
        # The evaluators read this rather than re-deriving it from the span
        # tree: it is the exact list of commands that actually ran.
        set_eval_attribute("ran_commands", [
            str(c["input"].get("command", "")) for c in tool_calls
        ])
        return final_text

    return task


# --------------------------------------------------------------------------
# Evaluators -- three dimensions, all deterministic
#
# Each takes its expectations as constructor arguments supplied per case in
# cases.json. None of them computes what it expects: an evaluator that derives
# its own ground truth from the system under test cannot detect that system
# regressing.
# --------------------------------------------------------------------------

@dataclass
class ScriptExecuted(Evaluator[str, str]):
    """Mechanism: did the turn actually run the tool it was supposed to?

    `required_tool_calls` is a list of substrings that must ALL appear in one
    single successful command -- so a case naming the script plus both dates
    demands one call carrying all three, not three unrelated calls that happen
    to mention them between them.

    Substrings rather than exact commands because the absolute skill path
    varies by checkout and the session quotes its arguments inconsistently.
    """

    required_tool_calls: list[str] = field(default_factory=list)
    evaluation_name: str = "script_executed"

    def evaluate(self, ctx: EvaluatorContext[str, str]) -> EvaluationReason:
        commands = ctx.attributes.get("ran_commands") or []
        for cmd in commands:
            if all(sub in cmd for sub in self.required_tool_calls):
                return EvaluationReason(value=True, reason=f"ran: {cmd[:160]}")
        if not commands:
            return EvaluationReason(value=False, reason="no tool call completed successfully")
        missing = [s for s in self.required_tool_calls
                   if not any(s in c for c in commands)]
        return EvaluationReason(
            value=False,
            reason=(f"no single successful command contained all of "
                    f"{self.required_tool_calls}"
                    + (f"; never seen at all: {missing}" if missing else "")),
        )


@dataclass
class DayCoverage(Evaluator[str, str]):
    """Completeness: is every expected day present in the response?

    Checks structure, not items. A day the script reports as empty still has
    to appear -- silently dropping quiet days is the failure this catches, and
    it is why the empty-window case is worth having.

    Dates are matched in several notations because the response is prose:
    2026-08-10, 08/10, 08-10, "Aug 10" and "August 10" all count. Matching a
    single notation would fail correct answers over formatting.
    """

    expected_days: list[str] = field(default_factory=list)
    evaluation_name: str = "day_coverage"

    def evaluate(self, ctx: EvaluatorContext[str, str]) -> EvaluationReason:
        output = ctx.output or ""
        missing = [d for d in self.expected_days if not _mentions_date(output, d)]
        if missing:
            return EvaluationReason(
                value=False,
                reason=f"{len(missing)} of {len(self.expected_days)} days absent: {', '.join(missing)}",
            )
        return EvaluationReason(
            value=True,
            reason=f"all {len(self.expected_days)} expected days present",
        )


@dataclass
class GroundedIdentifiers(Evaluator[str, str]):
    """Grounding: are the ticket numbers exactly the ones that belong here?

    Set equality against `expected_identifiers`, which makes this a two-sided
    check with one comparison: a number not in the list is fabrication, and a
    number in the list but absent from the response is compression -- a day
    collapsed into "10 items including...". Both are failures, and neither
    needs a judge to have an opinion.

    Numbers are compared without their repo prefix. Responses write bare "#61"
    when context makes the repo obvious, and demanding the prefix would fail
    correct answers; the cost is that the same number in two repos is
    indistinguishable here.
    """

    expected_identifiers: list[int] = field(default_factory=list)
    evaluation_name: str = "grounded_identifiers"

    def evaluate(self, ctx: EvaluatorContext[str, str]) -> EvaluationReason:
        expected = set(self.expected_identifiers)
        found = {int(n) for n in re.findall(r"#(\d+)", ctx.output or "")}

        fabricated = found - expected
        omitted = expected - found
        if fabricated or omitted:
            parts = []
            if fabricated:
                parts.append(f"{len(fabricated)} not expected ({_preview(fabricated)})")
            if omitted:
                parts.append(f"{len(omitted)} expected but missing ({_preview(omitted)})")
            return EvaluationReason(value=False, reason="; ".join(parts))

        if not expected:
            return EvaluationReason(value=True, reason="nothing expected and no identifiers invented")
        return EvaluationReason(value=True, reason=f"all {len(expected)} expected ticket numbers present, none extra")


def _mentions_date(text: str, iso: str) -> bool:
    d = date.fromisoformat(iso)
    variants = [
        iso,
        f"{d.month:02d}/{d.day:02d}",
        f"{d.month:02d}-{d.day:02d}",
        f"{d.strftime('%b')} {d.day}",
        f"{d.strftime('%B')} {d.day}",
    ]
    return any(v.lower() in text.lower() for v in variants)


def _preview(numbers: set[int], limit: int = 5) -> str:
    ordered = sorted(numbers)
    shown = ", ".join(f"#{n}" for n in ordered[:limit])
    return shown + (f", +{len(ordered) - limit} more" if len(ordered) > limit else "")


_JUDGE_VERDICT_RE = re.compile(r"^\s*(PASS|FAIL)\b", re.IGNORECASE)


@dataclass
class ClaudeCLIJudge(Evaluator[str, str]):
    """Rubric judging of the TEC report, via the authenticated `claude` CLI.

    The only non-deterministic evaluator here. It exists because the report's
    contract is a *shape* -- section order, real `<ul>` lists, synthesising
    prose, no leftover template comments -- and a shape is not a literal any
    matcher can hold.

    The rubric is supplied per case rather than shared, for the same reason
    every other expectation in this suite is: the cases differ in what a
    correct answer contains, not merely in a parameter. A shared rubric would
    have to be written vaguely enough to pass all three, which is how an eval
    stops measuring.

    An alternative to pydantic_evals' built-in LLMJudge, which needs a
    pydantic_ai client backed by a provider API key. This shells out the same
    way the task does, reusing the CLI's existing auth.
    """

    rubric: str = ""
    model: str = DEFAULT_MODEL
    evaluation_name: str = "tec_report"

    async def evaluate(self, ctx: EvaluatorContext[str, str]) -> EvaluationReason:
        judge_prompt = (
            "You are grading whether a response satisfies a rubric. "
            "Do not use any tools -- just reply directly.\n\n"
            f"Rubric:\n{self.rubric}\n\n"
            f"Response to grade:\n{ctx.output}\n\n"
            "Reply with exactly one line starting with PASS or FAIL, then one "
            "sentence naming the first rule violated."
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
            return EvaluationReason(value=False, reason=f"judge returned non-JSON: {proc.stdout[:300]}")
        match = _JUDGE_VERDICT_RE.match(result_text)
        if not match:
            return EvaluationReason(value=False, reason=f"judge reply didn't start with PASS/FAIL: {result_text[:300]}")
        return EvaluationReason(value=match.group(1).upper() == "PASS", reason=result_text.strip())


@dataclass
class PlanMatches(Evaluator[str, str]):
    """Did the turn write the plan file the case expects? (workday-timelogger)

    Deterministic: the expectation is literal data in cases.json. Compares the
    (date, entry, hours) sequence exactly, and the comment text wherever the
    case states one. The file is what the next workflow step consumes, so it is
    the thing to grade -- not the prose tables the turn prints alongside it.
    """

    plan_path: str = ""
    expected_entries: list[dict] = field(default_factory=list)
    evaluation_name: str = "plan_matches"

    def evaluate(self, ctx: EvaluatorContext[str, str]) -> EvaluationReason:
        path = Path(self.plan_path)
        if not path.exists():
            return EvaluationReason(value=False, reason=f"plan file not written: {path}")
        try:
            plan = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            return EvaluationReason(value=False, reason=f"plan file is not JSON: {e}")
        got = [(e.get("date"), e.get("entry"), e.get("hours")) for e in plan.get("entries", [])]
        want = [(e["date"], e["entry"], e["hours"]) for e in self.expected_entries]
        if got != want:
            return EvaluationReason(value=False, reason=f"entries {got} != expected {want}")
        for e, g in zip(self.expected_entries, plan["entries"]):
            if "comment" in e and e["comment"] != g.get("comment"):
                return EvaluationReason(
                    value=False,
                    reason=f"{e['date']} {e['entry']} comment {g.get('comment')!r} != {e['comment']!r}",
                )
        return EvaluationReason(value=True, reason=f"{len(want)} entries match")


@dataclass
class NoCommandContaining(Evaluator[str, str]):
    """Negative mechanism check: no successful command contained ALL of these
    substrings. The inverse of ScriptExecuted, for cases whose correct
    behaviour is to NOT act (a dry run must not click Send)."""

    forbidden: list[str] = field(default_factory=list)
    evaluation_name: str = "no_command_containing"

    def evaluate(self, ctx: EvaluatorContext[str, str]) -> EvaluationReason:
        commands = ctx.attributes.get("ran_commands") or []
        for cmd in commands:
            if all(sub in cmd for sub in self.forbidden):
                return EvaluationReason(value=False, reason=f"forbidden command ran: {cmd[:160]}")
        return EvaluationReason(value=True, reason=f"no command contained all of {self.forbidden}")


@dataclass
class AuditOutcome(Evaluator[str, str]):
    """Workflow-level check (weekly-log): the newest run directory under
    `runs_dir` must carry a `run` record with the expected outcome, and -- when
    stated -- the expected origin step. Reads the harness's own audit log, which
    is the artifact the workflow exists to produce."""

    runs_dir: str = "workflow/runs"
    expected_outcome: str = "success"
    expected_origin_step: str | None = None
    evaluation_name: str = "audit_outcome"

    def evaluate(self, ctx: EvaluatorContext[str, str]) -> EvaluationReason:
        root = Path(self.runs_dir)
        if not root.is_absolute():
            root = REPO_ROOT / root
        run_dirs = sorted(d for d in root.glob("*") if (d / "audit.jsonl").exists())
        if not run_dirs:
            return EvaluationReason(value=False, reason=f"no run with audit.jsonl under {root}")
        latest = run_dirs[-1]
        records = [json.loads(l) for l in (latest / "audit.jsonl").read_text().splitlines() if l.strip()]
        run_rec = next((r for r in records if r.get("kind") == "run"), None)
        if run_rec is None:
            return EvaluationReason(value=False, reason=f"{latest.name}: no run record (harness did not finish)")
        if run_rec.get("outcome") != self.expected_outcome:
            return EvaluationReason(value=False, reason=f"{latest.name}: outcome {run_rec.get('outcome')!r} != {self.expected_outcome!r}")
        if self.expected_origin_step and run_rec.get("origin_step") != self.expected_origin_step:
            return EvaluationReason(value=False, reason=f"{latest.name}: origin_step {run_rec.get('origin_step')!r} != {self.expected_origin_step!r}")
        return EvaluationReason(value=True, reason=f"{latest.name}: {run_rec.get('outcome')}")


CUSTOM_EVALUATORS = [ScriptExecuted, DayCoverage, GroundedIdentifiers, ClaudeCLIJudge,
                     PlanMatches, NoCommandContaining, AuditOutcome]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("skill", help="Skill directory name under .claude/skills/")
    parser.add_argument("--repeat", type=int, default=1, help="Times to repeat each case (default 1)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model for the task turns and the judge (default {DEFAULT_MODEL})")
    args = parser.parse_args()

    cases_path = REPO_ROOT / ".claude" / "skills" / args.skill / "evals" / "cases.json"
    if not cases_path.exists():
        sys.exit(f"No eval cases found at {cases_path}")

    dataset = Dataset.from_file(cases_path, custom_evaluator_types=CUSTOM_EVALUATORS)

    # Three evaluators need no model; the judge does. Every evaluator is
    # attached per case, so that is the only place to look.
    for case in dataset.cases:
        for evaluator in case.evaluators:
            if isinstance(evaluator, ClaudeCLIJudge):
                evaluator.model = args.model

    n_cases = len(dataset.cases)
    est_total = n_cases * args.repeat * EST_COST_PER_CASE_USD
    print(
        f"Running {n_cases} case(s) x {args.repeat} repeat(s) for '{args.skill}' on {args.model} "
        f"-- estimated cost: ~${est_total:.2f} floor (three evaluators are free; the judge costs one turn per case)"
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
    # include_reasons matters: without it a failure prints as a bare "x" and the
    # only way to learn why is to open the Logfire trace. Every evaluator here
    # returns a reason naming the specific dates or numbers at fault.
    report.print(include_input=False, include_output=False, include_reasons=True)

    if os.environ.get("LOGFIRE_TOKEN") and report.trace_id:
        print(f"\nView this run in Logfire: {logfire_trace_link(report.trace_id, run_started, run_ended)}")


if __name__ == "__main__":
    main()
