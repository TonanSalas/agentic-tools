"""g3_entry_check: what Workday shows after entry must equal what was planned."""
from __future__ import annotations

from collections import defaultdict

from . import GuardrailResult

OK_STATUSES = {"Entered", "Already filled", "Locked"}


def check_entry(plan: dict, entry_result: dict) -> GuardrailResult:
    if entry_result.get("error"):
        return GuardrailResult.fail(f"entry step reported an error: {entry_result['error']}")
    entries = entry_result.get("entries")
    totals = entry_result.get("totals")
    if not isinstance(entries, list) or not isinstance(totals, dict):
        return GuardrailResult.fail("entry result lacks entries[] or totals{}")
    planned = defaultdict(float)
    for e in plan.get("entries", []):
        planned[str(e["date"])] += float(e["hours"])
    reported = {(str(e.get("date")), e.get("entry")): e for e in entries}
    for e in plan.get("entries", []):
        key = (str(e["date"]), e["entry"])
        if key not in reported:
            return GuardrailResult.fail(f"{key[0]} {key[1]}: no status reported")
        st = reported[key].get("status")
        if st not in OK_STATUSES:
            return GuardrailResult.fail(f"{key[0]} {key[1]}: status {st!r} is not one of {sorted(OK_STATUSES)}")
    for d, hours in planned.items():
        if d not in totals:
            return GuardrailResult.fail(f"{d}: no weekly-view total read back")
        try:
            got = float(totals[d])
        except (TypeError, ValueError):
            return GuardrailResult.fail(f"{d}: total {totals[d]!r} is not a number")
        if abs(got - hours) > 1e-9:
            return GuardrailResult.fail(f"{d}: Workday shows {got}h, plan says {hours}h")
    return GuardrailResult.ok(f"{len(planned)} day totals match the plan")
