#!/usr/bin/env python3
"""Build the Workday entry plan from an hours string and weekly-activity YAML.

Pure logic: no browser, no network. SKILL.md Phase 2 and the weekly-log harness
both call this so the split / ticket-distribution / comment rules live in one
tested place instead of being re-derived in prose on every run.

    python3 plan_entries.py --hours "Mon 11, Tue 8" --week-start 2026-09-14 \
        [--activity s1_activity.yaml] [--today 2026-09-13] [--out plan.json]

Output JSON:
    {"week_start": "...", "entries": [{date, day, entry: Reg|Extra, hours,
     comment, tickets: [...]}], "issues": [{ref, title}]}
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, timedelta
from pathlib import Path

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_REG = 8
MAX_EXTRA = 3
MAX_TOTAL = 11
MAX_COMMENT = 255
PLACEHOLDER = "Activity placeholder"

_HOURS_RE = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+(\d+(?:\.\d+)?)", re.I)


def parse_hours(text: str) -> dict[str, float]:
    """'Mon 11, Tue 8' -> {'Mon': 11.0, 'Tue': 8.0}. Rejects hours outside (0, 11]."""
    out: dict[str, float] = {}
    for day, hrs in _HOURS_RE.findall(text):
        h = float(hrs)
        if h <= 0 or h > MAX_TOTAL:
            raise ValueError(f"{day}: {h} hours is outside 0 < h <= {MAX_TOTAL}")
        out[day[:3].title()] = h
    if not out:
        raise ValueError(f"no 'Day N' pairs found in {text!r}")
    return out


def _items_for(activity: dict | None, d: date) -> list[dict]:
    """Tickets recorded for one date, minus unresolved '(unknown #N)' cross-refs."""
    if not activity:
        return []
    for day in activity.get("days") or []:
        if str(day.get("date")) == d.isoformat():
            return [i for i in (day.get("items") or [])
                    if "(unknown #" not in str(i.get("title", ""))]
    return []


def _num(h: float) -> float | int:
    return int(h) if float(h).is_integer() else h


def _comment(items: list[dict]) -> str:
    if not items:
        return PLACEHOLDER
    full = ", ".join(f"{i['ref']}: {i['title']}" for i in items)
    if len(full) <= MAX_COMMENT:
        return full
    return ", ".join(i["ref"] for i in items)[:MAX_COMMENT]


def build_plan(hours: dict[str, float], week_start: date, activity: dict | None, today: date) -> dict:
    entries: list[dict] = []
    issues: dict[str, str] = {}
    for day in DAYS:
        if day not in hours:
            continue
        d = week_start + timedelta(days=DAYS.index(day))
        items = [] if d > today else _items_for(activity, d)
        for i in items:
            issues.setdefault(i["ref"], i["title"])
        total = float(hours[day])
        reg, extra = min(total, MAX_REG), max(0.0, total - MAX_REG)
        if extra > MAX_EXTRA:
            raise ValueError(f"{day}: {total}h exceeds {MAX_TOTAL}h")
        if extra and len(items) > 1:
            n_reg = math.ceil(len(items) * reg / total)
            reg_items, extra_items = items[:n_reg], items[n_reg:] or items[-1:]
        else:
            reg_items, extra_items = items, items

        def entry(kind: str, h: float, its: list[dict]) -> dict:
            return {"date": d.isoformat(), "day": day, "entry": kind, "hours": _num(h),
                    "comment": _comment(its), "tickets": [i["ref"] for i in its]}

        entries.append(entry("Reg", reg, reg_items))
        if extra:
            entries.append(entry("Extra", extra, extra_items))
    return {"week_start": week_start.isoformat(), "entries": entries,
            "issues": [{"ref": r, "title": t} for r, t in issues.items()]}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hours", required=True, help='e.g. "Mon 11, Tue 8"')
    p.add_argument("--week-start", required=True, help="Monday of the target week, YYYY-MM-DD")
    p.add_argument("--activity", help="weekly-activity YAML output file")
    p.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    p.add_argument("--out", help="write the plan JSON here as well as stdout")
    a = p.parse_args(argv)
    activity = None
    if a.activity:
        import yaml  # local import: only needed when an activity file is given
        activity = yaml.safe_load(Path(a.activity).read_text())
    today = date.fromisoformat(a.today) if a.today else date.today()
    plan = build_plan(parse_hours(a.hours), date.fromisoformat(a.week_start), activity, today)
    text = json.dumps(plan, indent=2)
    if a.out:
        Path(a.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
