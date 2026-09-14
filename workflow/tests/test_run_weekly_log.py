import json
from datetime import date
from pathlib import Path

import yaml

from workflow import run_weekly_log as h
from workflow.audit import read_audit
from workflow.guardrails import GuardrailResult
from workflow.steps import StepResult

START, END, TODAY = "2026-09-14", "2026-09-15", date(2026, 9, 20)
SUMMARY = ("<html><b>TEC Weekly Status Report – Dragonfly</b><br><b>Project:</b> Dragonfly<br><b>Date:</b> September 15, 2026<br>"
           "<b>Status:</b> 🟢<br><br><b>Summary</b><br>Did one thing.<br><b>Accomplished</b><ul><li>One</li></ul>"
           "<b>Planned Activities</b><ul></ul><b>Risks</b><br>No risks identified at the moment.</html>")
ACTIVITY = {"range": {"start": START, "end": END},
            "days": [{"date": START, "items": [{"ref": "ao#1", "title": "One"}], "summary": "x"},
                     {"date": END, "items": [], "summary": "quiet"}],
            "summary": SUMMARY}
PLAN = {"week_start": START, "entries": [
    {"date": START, "day": "Mon", "entry": "Reg", "hours": 8, "comment": "ao#1: One", "tickets": ["ao#1"]},
    {"date": END, "day": "Tue", "entry": "Reg", "hours": 8, "comment": "Activity placeholder", "tickets": []}], "issues": []}
ENTRY = {"entries": [{"date": START, "entry": "Reg", "hours": 8, "status": "Entered"},
                     {"date": END, "entry": "Reg", "hours": 8, "status": "Entered"}],
         "totals": {START: 8, END: 8}, "screenshot": "x.png"}


def ok(text="done", cost=0.5) -> StepResult:
    return StepResult(text=text, total_cost_usd=cost, input_tokens=100, output_tokens=20,
                      model_usage={"m": {"costUSD": cost}}, is_error=False, duration_ms=5, num_turns=1, session_id="s")


class FakeRunner:
    def __init__(self, s1_text=None, plan=PLAN, entry=ENTRY, fail_step=None):
        self.s1_text = s1_text or "```yaml\n" + yaml.safe_dump(ACTIVITY, sort_keys=False, allow_unicode=True) + "```"
        self.plan, self.entry, self.fail_step = plan, entry, fail_step
        self.calls: list[str] = []

    def __call__(self, step_id, prompt, run_dir, model):
        self.calls.append(step_id)
        if step_id == self.fail_step:
            r = ok(); r.is_error, r.error = True, "boom"; return r
        if step_id == "s1_activity":
            return ok(self.s1_text)
        if step_id == "s2a_plan":
            (run_dir / "s2a_plan.json").write_text(json.dumps(self.plan)); return ok("planned")
        if step_id == "s2b_enter":
            (run_dir / "s2b_enter.json").write_text(json.dumps(self.entry)); return ok("entered")
        return ok()


def reviewer_ok(html, cache, run_dir):
    return GuardrailResult.ok("clean"), ok("[]", 0.01)


def make_ctx(tmp_path, runner, cache: dict | None = None, **over) -> h.Context:
    if cache is not None:
        h.CACHE_DIR = tmp_path / "cache"; h.CACHE_DIR.mkdir(exist_ok=True)
        (h.CACHE_DIR / f"{START}_{END}.json").write_text(json.dumps(cache))
    kw = dict(run_id="r1", run_dir=tmp_path / "runs" / "r1", start=START, end=END, hours="Mon 8, Tue 8",
              today=TODAY, runner=runner, reviewer=reviewer_ok, interactive=False)
    kw.update(over)
    return h.Context(**kw)


CACHE = {"tickets": [{"repo": "ao", "number": 1, "title": "One", "state": "closed", "merged": True, "days": [START]}],
         "days": {START: [{"repo": "ao", "number": 1, "title": "One"}]}}


def ids(run_dir):
    return [r["id"] for r in read_audit(run_dir)]


def test_happy_path_pauses_at_p1_then_resumes_to_success(tmp_path, monkeypatch):
    runner = FakeRunner()
    ctx = make_ctx(tmp_path, runner, cache=CACHE)
    assert h.sequence(ctx) == h.AWAITING
    assert ids(ctx.run_dir) == ["s1_activity", "g1_activity_check", "g1_adversarial", "g1_adversarial",
                                "s2a_plan", "g2_plan_check", "s2b_enter", "g3_entry_check", h.P1, "r1"]
    assert runner.calls == ["s1_activity", "s2a_plan", "s2b_enter"]
    # human approves
    (ctx.run_dir / f"approved-{h.P1}.sentinel").write_text("ok")
    ctx2 = make_ctx(tmp_path, runner)
    assert h.sequence(ctx2) == h.SUCCESS
    assert runner.calls == ["s1_activity", "s2a_plan", "s2b_enter", "s2c_submit", "s3_send"]
    recs = read_audit(ctx.run_dir)
    run_recs = [r for r in recs if r["kind"] == "run"]
    assert [r["outcome"] for r in run_recs] == [h.AWAITING, h.SUCCESS]
    assert run_recs[-1]["total_cost_usd"] > 0
    assert (ctx.run_dir / "s3_message.html").read_text() == SUMMARY
    assert (ctx.run_dir / "teams-target.txt").read_text() == h.SELF_CHAT
    step = next(r for r in recs if r["id"] == "s1_activity")
    assert step["model"] == "m" and step["input_tokens"] == 100 and step["cost_usd"] == 0.5


def test_tampered_activity_fails_at_g1_and_stops(tmp_path):
    bad = dict(ACTIVITY); bad["days"] = [dict(ACTIVITY["days"][0], items=[{"ref": "ao#999", "title": "Fake"}]), ACTIVITY["days"][1]]
    runner = FakeRunner(s1_text=yaml.safe_dump(bad, sort_keys=False, allow_unicode=True))
    ctx = make_ctx(tmp_path, runner, cache=CACHE)
    assert h.sequence(ctx) == h.FAILED
    run_rec = read_audit(ctx.run_dir)[-1]
    assert run_rec["origin_step"] == "s1_activity" and "ao#999" in run_rec["reason"]
    assert runner.calls == ["s1_activity"]


def test_step_error_fails_with_origin(tmp_path):
    runner = FakeRunner(fail_step="s2a_plan")
    ctx = make_ctx(tmp_path, runner, cache=CACHE)
    assert h.sequence(ctx) == h.FAILED
    assert read_audit(ctx.run_dir)[-1]["origin_step"] == "s2a_plan"


def test_dry_run_skips_entry_and_submit(tmp_path):
    runner = FakeRunner()
    ctx = make_ctx(tmp_path, runner, cache=CACHE, dry_run=True)
    assert h.sequence(ctx) == h.SUCCESS
    assert runner.calls == ["s1_activity", "s2a_plan", "s3_send"]
    assert "s2b_enter" in ids(ctx.run_dir)  # recorded as skipped
    assert next(r for r in read_audit(ctx.run_dir) if r["id"] == "s2b_enter")["outcome"] == "skipped"


def test_skip_workday_goes_straight_to_teams(tmp_path):
    runner = FakeRunner()
    ctx = make_ctx(tmp_path, runner, cache=CACHE, skip_workday=True)
    assert h.sequence(ctx) == h.SUCCESS
    assert runner.calls == ["s1_activity", "s3_send"]


def test_other_teams_target_requires_p2(tmp_path):
    runner = FakeRunner()
    ctx = make_ctx(tmp_path, runner, cache=CACHE, skip_workday=True, teams_target="Dragonfly Team")
    assert h.sequence(ctx) == h.AWAITING
    assert read_audit(ctx.run_dir)[-2]["id"] == h.P2
    assert (ctx.run_dir / "teams-target.txt").read_text() == "Dragonfly Team"


def test_blocked_send_after_approval_is_a_failure(tmp_path):
    class Blocking(FakeRunner):
        def __call__(self, step_id, prompt, run_dir, model):
            r = super().__call__(step_id, prompt, run_dir, model)
            if step_id == "s3_send":
                r.blocked_calls = [{"name": "Bash", "input": {"command": "npx ... click e1"}, "error": "BLOCKED sentinel"}]
            return r
    ctx = make_ctx(tmp_path, Blocking(), cache=CACHE, skip_workday=True)
    assert h.sequence(ctx) == h.FAILED
    assert read_audit(ctx.run_dir)[-1]["origin_step"] == "s3_send"


def test_next_monday():
    assert h.next_monday(date(2026, 9, 13)) == date(2026, 9, 14)   # Sunday
    assert h.next_monday(date(2026, 9, 14)) == date(2026, 9, 21)   # Monday -> next week
    assert h.next_monday(date(2026, 9, 16)) == date(2026, 9, 21)


def test_build_context_test_mode_and_resume(tmp_path, monkeypatch):
    import argparse
    args = argparse.Namespace(resume=None, test=True, week=None, hours=None, teams_target=h.SELF_CHAT,
                              skip_workday=False, skip_teams=False, dry_run=True, model="m", runs_dir=str(tmp_path))
    ctx = h.build_context(args, today=date(2026, 9, 13))
    assert (ctx.start, ctx.end, ctx.hours, ctx.mode, ctx.dry_run) == ("2026-09-14", "2026-09-15", "Mon 8, Tue 8", "test", True)
    ctx.runner, ctx.reviewer, ctx.today = FakeRunner(), reviewer_ok, TODAY
    h.CACHE_DIR = tmp_path / "nocache"
    assert h.sequence(ctx) == h.SUCCESS
    args2 = argparse.Namespace(resume=ctx.run_id, model="m", runs_dir=str(tmp_path))
    ctx2 = h.build_context(args2, today=date(2026, 9, 13))
    assert (ctx2.start, ctx2.hours, ctx2.mode, ctx2.dry_run) == (ctx.start, ctx.hours, "test", True)


def test_inject_fault_s1_is_caught_by_g1(tmp_path):
    runner = FakeRunner()
    ctx = make_ctx(tmp_path, runner, cache=CACHE, inject_fault="s1_activity")
    assert h.sequence(ctx) == h.FAILED
    recs = read_audit(ctx.run_dir)
    assert [r["id"] for r in recs] == ["s1_activity", "inject_s1_activity", "g1_activity_check", "r1"]
    assert recs[-1]["origin_step"] == "s1_activity" and "agentic-org#99999" in recs[-1]["reason"]
