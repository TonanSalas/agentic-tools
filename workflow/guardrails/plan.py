"""g2_plan_check: the Workday entry plan must obey the hour rules and only
reference tickets that the activity step actually reported for that day."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import GuardrailResult

MAX_REG, MAX_EXTRA, MAX_TOTAL, MAX_COMMENT = 8, 3, 11, 255
PLACEHOLDER = "Activity placeholder"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _activity_refs(activity: dict | None) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for d in (activity or {}).get("days") or []:
        for item in d.get("items") or []:
            out[str(d.get("date"))].add(str(item.get("ref")))
    return out


def check_plan(plan: dict, hours: dict[str, float], activity: dict | None, today: date) -> GuardrailResult:
    entries = plan.get("entries")
    if not isinstance(entries, list) or not entries:
        return GuardrailResult.fail("plan has no entries")
    by_date: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_date[str(e.get("date"))].append(e)

    planned_days = {e.get("day") for e in entries}
    if planned_days != set(hours):
        return GuardrailResult.fail(f"planned days {sorted(planned_days)} != requested {sorted(hours)}")

    refs_by_date = _activity_refs(activity)
    for d, es in by_date.items():
        day = es[0].get("day")
        total = sum(float(e.get("hours", 0)) for e in es)
        if abs(total - float(hours.get(day, -1))) > 1e-9:
            return GuardrailResult.fail(f"{d}: planned {total}h != requested {hours.get(day)}h")
        if total > MAX_TOTAL:
            return GuardrailResult.fail(f"{d}: {total}h exceeds {MAX_TOTAL}h")
        kinds = [e.get("entry") for e in es]
        if kinds not in (["Reg"], ["Reg", "Extra"]):
            return GuardrailResult.fail(f"{d}: entry kinds {kinds} must be [Reg] or [Reg, Extra]")
        for e in es:
            h = float(e.get("hours", 0))
            cap = MAX_REG if e.get("entry") == "Reg" else MAX_EXTRA
            if h <= 0 or h > cap:
                return GuardrailResult.fail(f"{d} {e.get('entry')}: {h}h outside (0, {cap}]")
            comment = str(e.get("comment", ""))
            if not comment or len(comment) > MAX_COMMENT:
                return GuardrailResult.fail(f"{d} {e.get('entry')}: comment empty or > {MAX_COMMENT} chars")
            if "(unknown #" in comment:
                return GuardrailResult.fail(f"{d}: comment carries an unresolved '(unknown #N)' ticket")
            tickets = [str(t) for t in e.get("tickets") or []]
            if date.fromisoformat(d) > today:
                if tickets or comment != PLACEHOLDER:
                    return GuardrailResult.fail(f"{d} is in the future but has tickets or a non-placeholder comment")
                continue
            if not tickets and comment != PLACEHOLDER:
                return GuardrailResult.fail(f"{d} {e.get('entry')}: no tickets but comment is not the placeholder")
            unknown = sorted(set(tickets) - refs_by_date.get(d, set()))
            if unknown:
                return GuardrailResult.fail(f"{d}: ticket(s) not reported by weekly-activity for that day: {', '.join(unknown)}")
    return GuardrailResult.ok(f"{len(entries)} entries over {len(by_date)} days within limits and grounded")
