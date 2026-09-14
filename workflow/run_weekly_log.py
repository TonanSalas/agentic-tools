#!/usr/bin/env python3
"""weekly-log harness: weekly-activity -> workday-timelogger -> teams-messenger.

    python3 workflow/run_weekly_log.py --week 2026-09-14..2026-09-18 --hours "Mon 8, Tue 8, Wed 8, Thu 8, Fri 8"
    python3 workflow/run_weekly_log.py --test                 # next Mon/Tue, 8h each, self-chat
    python3 workflow/run_weekly_log.py --resume <run_id>      # continue after writing a sentinel

Each step is a headless Claude turn; every handoff is a file in
workflow/runs/<run_id>/; guardrails run in this process between steps; the
two punch-outs wait for a human sentinel; audit.jsonl records everything with
per-step model/token/cost data.
"""
from __future__ import annotations

# Allow `python3 workflow/<file>.py` as well as `python3 -m workflow.<file>`.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    import importlib as _il
    _sys.exit(_il.import_module("workflow." + _P(__file__).stem).main())

import argparse
import json
import re
import secrets
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import prompts
from .audit import Audit, read_audit
from .guardrails import GuardrailResult, adversarial
from .guardrails.activity import check_activity
from .guardrails.entry import check_entry
from .guardrails.message import check_message, summary_from_yaml
from .guardrails.plan import check_plan
from .steps import REPO_ROOT, StepResult, run_step, usage_fields

sys.path.insert(0, str(REPO_ROOT / ".claude" / "skills" / "workday-timelogger" / "scripts"))
from plan_entries import parse_hours  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-5"
SELF_CHAT = "Tonan Salas (You)"
RUNS_DIR = REPO_ROOT / "workflow" / "runs"
CACHE_DIR = REPO_ROOT / ".claude" / "skills" / "weekly-activity" / "cache"

P1, P2 = "p1_submit_timesheet", "p2_send_to_others"
SUCCESS, FAILED, AWAITING, REJECTED = "success", "failed", "awaiting_human", "rejected_by_human"


class StopRun(Exception):
    def __init__(self, outcome: str, origin_step: str | None = None, reason: str = ""):
        super().__init__(reason)
        self.outcome, self.origin_step, self.reason = outcome, origin_step, reason


Runner = Callable[[str, str, Path, str], StepResult]
Reviewer = Callable[[str, dict, Path], tuple[GuardrailResult, StepResult]]


@dataclass
class Context:
    run_id: str
    run_dir: Path
    start: str
    end: str
    hours: str
    teams_target: str = SELF_CHAT
    skip_workday: bool = False
    skip_teams: bool = False
    dry_run: bool = False
    mode: str = "real"
    model: str = DEFAULT_MODEL
    today: date = field(default_factory=date.today)
    runner: Runner = lambda sid, prompt, run_dir, model: run_step(sid, prompt, run_dir, model)
    reviewer: Reviewer = lambda html, cache, run_dir: adversarial.review(html, cache, run_dir)
    interactive: bool = False
    inject_fault: str | None = None   # "s1_activity": append a fabricated ref after step 1 (guardrail demo)
    audit: Audit = field(init=False)

    def __post_init__(self):
        self.audit = Audit(self.run_dir, self.run_id)

    def path(self, name: str) -> Path:
        return self.run_dir / name


# ---------------------------------------------------------------- helpers

def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def next_monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def _strip_fences(text: str) -> str:
    m = re.search(r"```(?:yaml|yml|json)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _already_done(ctx: Context, step_id: str) -> bool:
    return any(r.get("id") == step_id and r.get("outcome") in ("success", "passed", "approved")
               for r in read_audit(ctx.run_dir))


def _log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- pieces

def do_step(ctx: Context, step_id: str, prompt: str) -> StepResult:
    _log(f"▶ {step_id}")
    r = ctx.runner(step_id, prompt, ctx.run_dir, ctx.model)
    fields = usage_fields(r)
    if r.is_error:
        ctx.audit.record("step", step_id, FAILED, error=r.error, **fields)
        raise StopRun(FAILED, step_id, f"{step_id}: {r.error}")
    ctx.audit.record("step", step_id, SUCCESS, **fields)
    _log(f"  ✓ {step_id}  model={fields['model']} in={fields['input_tokens']} out={fields['output_tokens']} cost=${fields['cost_usd']:.4f}")
    return r


def do_guardrail(ctx: Context, gid: str, result: GuardrailResult, checked: str, origin_step: str) -> None:
    ctx.audit.record("guardrail", gid, "passed" if result.passed else FAILED,
                     passed=result.passed, reason=result.reason, checked_output=checked, origin_step=origin_step)
    _log(f"  {'✓' if result.passed else '✗'} {gid}: {result.reason}")
    if not result.passed:
        raise StopRun(FAILED, origin_step, f"{gid}: {result.reason}")


def punch_out(ctx: Context, pid: str, evidence: str) -> None:
    sentinel = ctx.path(f"approved-{pid}.sentinel")
    if sentinel.exists():
        ctx.audit.record("punchout", pid, "approved", sentinel_path=str(sentinel), decision="approve",
                         decided_by="human (sentinel present)")
        _log(f"  ✓ {pid}: approved (sentinel present)")
        return
    _log(f"\n⏸ PUNCH-OUT {pid}: a human must decide.\n{evidence}\n")
    if ctx.interactive:
        ans = input(f"Type 'approve' to continue or 'reject' to stop [{pid}]: ").strip().lower()
        if ans == "approve":
            sentinel.write_text(f"approved by human at {datetime.now(timezone.utc).isoformat()}\n")
            ctx.audit.record("punchout", pid, "approved", sentinel_path=str(sentinel), decision="approve",
                             decided_by="human (terminal)")
            return
        ctx.audit.record("punchout", pid, REJECTED, sentinel_path=str(sentinel), decision="reject",
                         decided_by="human (terminal)")
        raise StopRun(REJECTED, None, f"{pid} rejected by human")
    ctx.audit.record("punchout", pid, AWAITING, sentinel_path=str(sentinel), decision=None, decided_by=None)
    _log(f"To approve, create the sentinel and resume:\n  touch '{sentinel}'\n"
         f"  python3 workflow/run_weekly_log.py --resume {ctx.run_id}")
    raise StopRun(AWAITING, None, f"{pid} awaiting human")


# ---------------------------------------------------------------- sequence

def sequence(ctx: Context) -> str:
    try:
        # s1 ----------------------------------------------------------------
        act_path = ctx.path("s1_activity.yaml")
        if not _already_done(ctx, "s1_activity"):
            r = do_step(ctx, "s1_activity", prompts.s1(ctx.start, ctx.end))
            act_path.write_text(_strip_fences(r.text), encoding="utf-8")
            if ctx.inject_fault == "s1_activity":
                _inject_fabricated_ref(act_path)
                ctx.audit.record("fault", "inject_s1_activity", "injected",
                                 reason="appended a fabricated ticket ref to s1_activity.yaml (demo of g1 catching fabrication)")
        yaml_text = act_path.read_text(encoding="utf-8")
        cache_path = CACHE_DIR / f"{ctx.start}_{ctx.end}.json"
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else None
        if not _already_done(ctx, "g1_activity_check"):
            res = check_activity(yaml_text, ctx.start, ctx.end, cache)
            if cache is None and res.passed:
                res = GuardrailResult(True, res.reason + " (no cache file: ref grounding not checked)")
            do_guardrail(ctx, "g1_activity_check", res, str(act_path), "s1_activity")
        if not _already_done(ctx, "g1_adversarial"):
            res, rr = ctx.reviewer(summary_from_yaml(yaml_text), cache or {"tickets": []}, ctx.run_dir)
            ctx.audit.record("step", "g1_adversarial", SUCCESS if not rr.is_error else FAILED, **usage_fields(rr))
            do_guardrail(ctx, "g1_adversarial", res, str(act_path), "s1_activity")

        # s2 ----------------------------------------------------------------
        if ctx.skip_workday:
            for sid in ("s2a_plan", "s2b_enter", P1, "s2c_submit"):
                ctx.audit.record("step" if sid != P1 else "punchout", sid, "skipped", reason="--skip-workday")
        else:
            plan_path = ctx.path("s2a_plan.json")
            if not _already_done(ctx, "s2a_plan"):
                do_step(ctx, "s2a_plan", prompts.s2a(ctx.hours, ctx.start, act_path, plan_path, ctx.today.isoformat()))
                if not plan_path.exists():
                    raise StopRun(FAILED, "s2a_plan", "plan file was not written")
            plan = json.loads(plan_path.read_text())
            if not _already_done(ctx, "g2_plan_check"):
                import yaml as _yaml
                activity = _yaml.safe_load(yaml_text)
                do_guardrail(ctx, "g2_plan_check", check_plan(plan, parse_hours(ctx.hours), activity, ctx.today),
                             str(plan_path), "s2a_plan")
            if ctx.dry_run:
                for sid in ("s2b_enter", "g3_entry_check", P1, "s2c_submit"):
                    ctx.audit.record("step", sid, "skipped", reason="--dry-run")
            else:
                entry_path = ctx.path("s2b_enter.json")
                if not _already_done(ctx, "s2b_enter"):
                    r = do_step(ctx, "s2b_enter", prompts.s2b(plan_path, entry_path))
                    if not entry_path.exists():
                        data = _extract_json(r.text)
                        if data is None:
                            raise StopRun(FAILED, "s2b_enter", "entry result file was not written")
                        entry_path.write_text(json.dumps(data, indent=2))
                entry = json.loads(entry_path.read_text())
                if not _already_done(ctx, "g3_entry_check"):
                    do_guardrail(ctx, "g3_entry_check", check_entry(plan, entry), str(entry_path), "s2b_enter")
                evidence = _plan_table(plan) + f"\nWorkday totals read back: {entry.get('totals')}\nScreenshot: {entry.get('screenshot')}"
                punch_out(ctx, P1, evidence)
                if not _already_done(ctx, "s2c_submit"):
                    r = do_step(ctx, "s2c_submit", prompts.s2c())
                    if r.blocked_calls:
                        ctx.audit.record("guardrail", "hook_p1", FAILED, reason="Submit click blocked by hook after approval",
                                         blocked=[c["input"].get("command") for c in r.blocked_calls], origin_step="s2c_submit")
                        raise StopRun(FAILED, "s2c_submit", "submit click was blocked by the sentinel hook")

        # s3 ----------------------------------------------------------------
        if ctx.skip_teams:
            ctx.audit.record("step", "s3_send", "skipped", reason="--skip-teams")
        else:
            msg_path = ctx.path("s3_message.html")
            msg_path.write_text(summary_from_yaml(yaml_text), encoding="utf-8")
            if not _already_done(ctx, "g4_message_check"):
                do_guardrail(ctx, "g4_message_check", check_message(msg_path.read_text(), yaml_text), str(msg_path), "s1_activity")
            ctx.path("teams-target.txt").write_text(ctx.teams_target)
            if ctx.teams_target != SELF_CHAT:
                punch_out(ctx, P2, f"Target chat: {ctx.teams_target}\nMessage: {msg_path}")
            else:
                ctx.audit.record("punchout", P2, "not_required", reason="target is the self-chat")
            if not _already_done(ctx, "s3_send"):
                r = do_step(ctx, "s3_send", prompts.s3(msg_path, ctx.teams_target, ctx.dry_run))
                if r.blocked_calls:
                    ctx.audit.record("guardrail", "hook_p2", FAILED, reason="Send click blocked by hook",
                                     blocked=[c["input"].get("command") for c in r.blocked_calls], origin_step="s3_send")
                    raise StopRun(FAILED, "s3_send", "send click was blocked by the sentinel hook")
        return _finish(ctx, SUCCESS)
    except StopRun as s:
        return _finish(ctx, s.outcome, s.origin_step, s.reason)


def _inject_fabricated_ref(act_path: Path) -> None:
    """Fault injection for the guardrail demo: add a ticket that the gathered data
    never contained to the first day, exactly what a hallucinating step would do."""
    import yaml as _yaml
    doc = _yaml.safe_load(act_path.read_text(encoding="utf-8"))
    doc["days"][0].setdefault("items", []).append({"ref": "agentic-org#99999", "title": "Fabricated item for guardrail demo"})
    act_path.write_text(_yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _plan_table(plan: dict) -> str:
    rows = ["| Day | Entry | Hours | Comment |", "|---|---|---|---|"]
    for e in plan.get("entries", []):
        rows.append(f"| {e['day']} {e['date']} | {e['entry']} | {e['hours']} | {e['comment'][:80]} |")
    return "\n".join(rows)


def _finish(ctx: Context, outcome: str, origin_step: str | None = None, reason: str = "") -> str:
    recs = read_audit(ctx.run_dir)
    cost = sum(float(r.get("cost_usd", 0) or 0) for r in recs if r.get("kind") == "step")
    ctx.audit.record("run", ctx.run_id, outcome, origin_step=origin_step, reason=reason,
                     total_cost_usd=round(cost, 4), mode=ctx.mode, start=ctx.start, end=ctx.end,
                     hours=ctx.hours, teams_target=ctx.teams_target, dry_run=ctx.dry_run,
                     skip_workday=ctx.skip_workday, skip_teams=ctx.skip_teams)
    _log(f"\n■ run {ctx.run_id}: {outcome}" + (f" (origin step {origin_step}: {reason})" if origin_step or reason else "")
         + f"  total cost ${cost:.4f}")
    return outcome


# ---------------------------------------------------------------- CLI

def build_context(args, today: date | None = None) -> Context:
    today = today or date.today()
    if args.resume:
        run_dir = Path(args.runs_dir) / args.resume
        run_rec = next((r for r in reversed(read_audit(run_dir)) if r.get("kind") == "run"), None)
        if run_rec is None:
            sys.exit(f"cannot resume {args.resume}: no run record")
        return Context(run_id=args.resume, run_dir=run_dir, start=run_rec["start"], end=run_rec["end"],
                       hours=run_rec["hours"], teams_target=run_rec["teams_target"], skip_workday=run_rec["skip_workday"],
                       skip_teams=run_rec["skip_teams"], dry_run=run_rec["dry_run"], mode=run_rec["mode"],
                       model=args.model, today=today, interactive=sys.stdin.isatty())
    if args.test:
        mon = next_monday(today)
        start, end, hours, mode = mon.isoformat(), (mon + timedelta(days=1)).isoformat(), "Mon 8, Tue 8", "test"
        target = SELF_CHAT
    else:
        if not args.week or not args.hours:
            sys.exit("--week and --hours are required (or --test)")
        start, end = args.week.split("..")
        hours, mode, target = args.hours, "real", args.teams_target
    parse_hours(hours)
    run_id = new_run_id()
    return Context(run_id=run_id, run_dir=Path(args.runs_dir) / run_id, start=start, end=end, hours=hours,
                   teams_target=target, skip_workday=args.skip_workday, skip_teams=args.skip_teams,
                   dry_run=args.dry_run, mode=mode, model=args.model, today=today, interactive=sys.stdin.isatty())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--week", help="YYYY-MM-DD..YYYY-MM-DD (Monday..last day)")
    p.add_argument("--hours", help='e.g. "Mon 8, Tue 8, Wed 8, Thu 8, Fri 8"')
    p.add_argument("--test", action="store_true", help="next Mon/Tue, 8h each, Teams self-chat")
    p.add_argument("--teams-target", default=SELF_CHAT)
    p.add_argument("--skip-workday", action="store_true")
    p.add_argument("--skip-teams", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="plan only in Workday; Teams --dry-run (nothing committed)")
    p.add_argument("--resume", metavar="RUN_ID")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--runs-dir", default=str(RUNS_DIR))
    p.add_argument("--inject-fault", choices=["s1_activity"],
                   help="tamper with a step's output on purpose to demonstrate the guardrail catching it")
    args = p.parse_args(argv)
    ctx = build_context(args)
    ctx.inject_fault = args.inject_fault
    if ctx.inject_fault:
        ctx.mode = f"fault-injection:{ctx.inject_fault}"
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    _log(f"run {ctx.run_id}  week {ctx.start}..{ctx.end}  hours '{ctx.hours}'  mode={ctx.mode}  dir={ctx.run_dir}")
    outcome = sequence(ctx)
    return 0 if outcome == SUCCESS else (3 if outcome == AWAITING else 1)


if __name__ == "__main__":
    sys.exit(main())
