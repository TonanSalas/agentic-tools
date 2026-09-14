from pathlib import Path

from workflow.audit import Audit
from workflow.report import render_markdown, summarize, load_runs


def _run(root: Path, run_id: str, outcome: str, origin: str | None = None, cost: float = 1.0):
    a = Audit(root / run_id, run_id)
    a.record("step", "s1_activity", "success", cost_usd=cost / 2, input_tokens=10, output_tokens=5, model="m")
    a.record("guardrail", "g1_activity_check", "passed")
    if outcome == "failed":
        a.record("guardrail", origin or "g2_plan_check", "failed", reason="bad", origin_step="s2a_plan")
    else:
        a.record("step", "s3_send", "success", cost_usd=cost / 2, input_tokens=10, output_tokens=5, model="m")
    a.record("run", run_id, outcome, origin_step="s2a_plan" if outcome == "failed" else None,
             total_cost_usd=cost, mode="test")


def test_summarize_and_render(tmp_path: Path):
    _run(tmp_path, "20260914-a", "success")
    _run(tmp_path, "20260915-b", "failed")
    _run(tmp_path, "20260916-c", "success")
    _run(tmp_path, "20260917-d", "awaiting_human")
    _run(tmp_path, "20260918-e", "rejected_by_human")
    s = summarize(load_runs(tmp_path))
    assert s["total"] == 5 and s["decided"] == 3 and s["success"] == 2 and s["rejected"] == 1
    assert round(s["rate"], 3) == 0.667
    assert [round(x, 3) for x in s["trend"]] == [1.0, 0.5, 0.667]
    assert s["per_run"][1]["origin_step"] == "s2a_plan"
    assert s["per_step"]["s1_activity"]["pass"] == 5
    md = render_markdown(s)
    assert "66.7%" in md and "20260915-b" in md and "s2a_plan" in md
