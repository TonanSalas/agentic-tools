#!/usr/bin/env python3
"""End-to-end success rate, per-run trend and failure tracing over audit logs.

    python3 workflow/report.py                      # print the report
    python3 workflow/report.py --out stage4/success-report.md
    python3 workflow/report.py --run <run_id>       # trace one run's records

The Stage 4 number is the END-TO-END rate: runs whose `run` record says
`success`, divided by runs that ended `success` or `failed`. Runs still
`awaiting_human`, and runs a human `rejected` at a punch-out, are listed but
not in the denominator: neither is a workflow failure.
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
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .audit import first_failure, read_audit

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "workflow" / "runs"


def load_runs(runs_dir: Path) -> list[list[dict]]:
    runs = []
    for d in sorted(Path(runs_dir).iterdir()):
        recs = read_audit(d) if d.is_dir() else []
        if any(r.get("kind") == "run" for r in recs) or any(r.get("kind") == "step" for r in recs):
            runs.append(recs)
    return runs


def summarize(runs: list[list[dict]]) -> dict:
    per_run, trend = [], []
    per_step: dict[str, dict] = defaultdict(lambda: {"pass": 0, "fail": 0})
    success = decided = rejected = 0
    for recs in runs:
        run_rec = next((r for r in reversed(recs) if r.get("kind") == "run"), None)   # last: a resumed run appends
        outcome = run_rec.get("outcome") if run_rec else "incomplete"
        run_id = (run_rec or recs[0]).get("run_id")
        cost = sum(float(r.get("cost_usd", 0) or 0) for r in recs if r.get("kind") == "step")
        tokens = sum(int(r.get("input_tokens", 0) or 0) + int(r.get("output_tokens", 0) or 0)
                     for r in recs if r.get("kind") == "step")
        ff = first_failure(recs)
        per_run.append({
            "run_id": run_id, "mode": (run_rec or {}).get("mode", ""), "outcome": outcome,
            "origin_step": (run_rec or {}).get("origin_step") or (ff or {}).get("origin_step") or (ff or {}).get("id"),
            "cost_usd": round(cost, 4), "tokens": tokens, "ts": recs[0].get("ts", ""),
        })
        for r in recs:
            # Count only real outcomes; skipped / not_required / awaiting / approved
            # records are neither a pass nor a fail of that step.
            if r.get("kind") in ("step", "guardrail") and r.get("outcome") in ("success", "passed", "failed"):
                key = "pass" if r.get("outcome") in ("success", "passed") else "fail"
                per_step[r["id"]][key] += 1
        if outcome in ("success", "failed"):
            decided += 1
            success += outcome == "success"
            trend.append(success / decided)
        elif outcome == "rejected_by_human":
            rejected += 1
    return {"total": len(runs), "decided": decided, "success": success, "rejected": rejected,
            "rate": (success / decided) if decided else 0.0, "per_run": per_run,
            "per_step": dict(per_step), "trend": trend}


def render_markdown(s: dict) -> str:
    lines = [
        "# weekly-log end-to-end success report", "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}", "",
        f"**End-to-end success rate: {s['rate']*100:.1f}%** ({s['success']} of {s['decided']} runs that ran to a workflow "
        f"outcome; {s['total']} runs total, {s.get('rejected', 0)} stopped by a human rejection at a punch-out, "
        f"{s['total']-s['decided']-s.get('rejected', 0)} still awaiting a human).", "",
        "Rate = success / (success + failed). A human rejection at a punch-out is a decision, not a workflow "
        "failure, and is listed but not counted against the workflow.", "",
        "## Per run", "", "| # | Run | Mode | Outcome | Origin step (if failed) | Cost USD | Tokens |", "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(s["per_run"], 1):
        lines.append(f"| {i} | {r['run_id']} | {r['mode']} | {r['outcome']} | {r['origin_step'] or ''} | {r['cost_usd']:.4f} | {r['tokens']} |")
    lines += ["", "## Trend (cumulative success rate after each decided run)", ""]
    lines.append(" → ".join(f"{x*100:.1f}%" for x in s["trend"]) or "(no decided runs)")
    lines += ["", "## Per step / guardrail pass rate", "", "| Id | Pass | Fail |", "|---|---|---|"]
    for sid, c in sorted(s["per_step"].items()):
        lines.append(f"| {sid} | {c['pass']} | {c['fail']} |")
    return "\n".join(lines) + "\n"


def trace_run(run_dir: Path) -> str:
    recs = read_audit(run_dir)
    out = [f"# {run_dir.name}", ""]
    for r in recs:
        extra = ""
        if r["kind"] == "step":
            extra = (f" model={r.get('model')} in={r.get('input_tokens')} cache_read={r.get('cache_read_tokens')} "
                     f"cache_write={r.get('cache_creation_tokens')} out={r.get('output_tokens')} cost=${float(r.get('cost_usd') or 0):.4f}")
        elif r["kind"] == "guardrail":
            extra = f" reason={r.get('reason')!r}"
        elif r["kind"] == "punchout":
            extra = f" decision={r.get('decision')} sentinel={r.get('sentinel_path')}"
        out.append(f"{r['ts']}  {r['kind']:9s} {r['id']:22s} {r['outcome']:16s}{extra}")
    ff = first_failure(recs)
    out += ["", f"First failure: {ff['id']} (origin step {ff.get('origin_step') or ff['id']}): {ff.get('reason', ff.get('error', ''))}" if ff else "No failure in this run."]
    return "\n".join(out) + "\n"


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p.add_argument("--out", help="also write the markdown report here")
    p.add_argument("--run", help="trace one run id instead of summarising")
    a = p.parse_args(argv)
    runs_dir = Path(a.runs_dir)
    if a.run:
        print(trace_run(runs_dir / a.run))
        return
    md = render_markdown(summarize(load_runs(runs_dir)))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
