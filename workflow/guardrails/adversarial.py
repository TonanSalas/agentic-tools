"""g1_adversarial: a second, cheaper model tries to find claims in the TEC
report that the gathered data does not support. Its cost is audited like any
step. Pass = it returns an empty JSON list."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..steps import StepResult, run_step
from . import GuardrailResult

ADVERSARIAL_MODEL = "claude-haiku-4-5-20251001"

RUBRIC = """You are an adversarial reviewer. Do not use any tools. Reply with JSON only.

Below is (A) the raw GitHub activity data gathered for one week, and (B) a status
report written from it. Your job is to find every claim in (B) that (A) does not
support: work items, repositories, features, people, blockers or risks that do not
appear in (A), or accomplishments that (A) shows as still open/unmerged.

Ignore wording, style and level of detail. Rephrasing a ticket title in plain words
is supported. Do not flag the absence of something. Do not flag the Date, Status
emoji or Project lines.

Reply with a JSON array of strings, one per unsupported claim, quoting the claim.
Reply with exactly [] if every claim is supported.

(A) DATA:
{data}

(B) REPORT:
{report}
"""

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.S)


def parse_claims(text: str) -> list[str] | None:
    m = _JSON_ARRAY_RE.search(text or "")
    if not m:
        return None
    try:
        val = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return [str(v) for v in val] if isinstance(val, list) else None


def _compact(cache_json: dict) -> str:
    rows = []
    for t in cache_json.get("tickets", []) or []:
        state = "merged" if t.get("merged") else t.get("state", "?")
        rows.append(f"- {t['repo']}#{t['number']} [{state}] {t.get('title','')} (days: {', '.join(t.get('days', []))})")
    return "\n".join(rows) or "(no activity)"


def review(summary_html: str, cache_json: dict, run_dir: Path, model: str = ADVERSARIAL_MODEL) -> tuple[GuardrailResult, StepResult]:
    prompt = RUBRIC.format(data=_compact(cache_json), report=summary_html)
    r = run_step("g1_adversarial", prompt, run_dir, model)
    if r.is_error:
        return GuardrailResult.fail(f"reviewer turn failed: {r.error}"), r
    claims = parse_claims(r.text)
    if claims is None:
        return GuardrailResult.fail(f"reviewer reply was not a JSON array: {r.text[:200]!r}"), r
    if claims:
        return GuardrailResult.fail(f"{len(claims)} unsupported claim(s): " + " | ".join(claims[:5])), r
    return GuardrailResult.ok("reviewer found no unsupported claims"), r
