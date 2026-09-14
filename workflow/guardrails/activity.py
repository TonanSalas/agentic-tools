"""g1_activity_check: validate weekly-activity's YAML before anything consumes it."""
from __future__ import annotations

import re
from datetime import date, timedelta

import yaml

from . import GuardrailResult

TEC_MARKERS = [
    "<b>TEC Weekly Status Report", "<b>Project:</b>", "<b>Date:</b>", "<b>Status:</b>",
    "<b>Summary</b>", "<b>Accomplished</b>", "<b>Planned Activities</b>", "<b>Risks</b>",
]
# `#123`, `repo#123`, `DRA-1234`; not HTML entities like `&#8217;`.
TICKET_RE = re.compile(r"(?<!&)(?:\b[\w.-]+)?#\d+\b|\bDRA-\d+\b")
REF_RE = re.compile(r"^([\w.-]+)#(\d+)$")


def refs_in_cache(cache_json: dict) -> set[str]:
    refs = set()
    for t in cache_json.get("tickets", []) or []:
        refs.add(f"{t['repo']}#{t['number']}")
    for items in (cache_json.get("days", {}) or {}).values():
        for t in items or []:
            refs.add(f"{t['repo']}#{t['number']}")
    return refs


def expected_dates(start: str, end: str) -> list[str]:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]


def check_activity(yaml_text: str, start: str, end: str, cache_json: dict | None) -> GuardrailResult:
    try:
        doc = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        return GuardrailResult.fail(f"YAML does not parse: {e}")
    if not isinstance(doc, dict):
        return GuardrailResult.fail("YAML top level is not a mapping")

    rng = doc.get("range") or {}
    if str(rng.get("start")) != start or str(rng.get("end")) != end:
        return GuardrailResult.fail(f"range {rng} != requested {start}..{end}")

    days = doc.get("days")
    if not isinstance(days, list):
        return GuardrailResult.fail("days is not a list")
    got = [str(d.get("date")) for d in days if isinstance(d, dict)]
    want = expected_dates(start, end)
    if got != want:
        return GuardrailResult.fail(f"days {got} != expected {want}")

    seen_refs: list[str] = []
    for d in days:
        for item in d.get("items") or []:
            ref = str(item.get("ref", ""))
            if not REF_RE.match(ref):
                return GuardrailResult.fail(f"{d.get('date')}: malformed ref {ref!r}")
            seen_refs.append(ref)
    if cache_json is not None:
        valid = refs_in_cache(cache_json)
        unknown = sorted(set(seen_refs) - valid)
        if unknown:
            return GuardrailResult.fail(f"{len(unknown)} ref(s) not in the gathered data (fabrication?): {', '.join(unknown[:8])}")
        missing = sorted(valid - set(seen_refs))
        if missing:
            return GuardrailResult.fail(f"{len(missing)} gathered ref(s) dropped from the YAML: {', '.join(missing[:8])}")

    summary = doc.get("summary")
    if not isinstance(summary, str) or "<b>" not in summary:
        return GuardrailResult.fail("summary is missing or not HTML")
    pos = -1
    for marker in TEC_MARKERS:
        i = summary.find(marker)
        if i < 0:
            return GuardrailResult.fail(f"summary lacks section marker {marker!r}")
        if i < pos:
            return GuardrailResult.fail(f"summary section {marker!r} is out of order")
        pos = i
    if "<!--" in summary:
        return GuardrailResult.fail("summary still contains template comments")
    m = TICKET_RE.search(summary)
    if m:
        return GuardrailResult.fail(f"summary contains a ticket number: {m.group(0)!r}")
    return GuardrailResult.ok(f"{len(days)} days, {len(seen_refs)} refs, TEC report well-formed")
