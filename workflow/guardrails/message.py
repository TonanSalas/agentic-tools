"""g4_message_check: the message handed to Teams is byte-for-byte the report
weekly-activity produced (modulo whitespace), and carries no ticket numbers."""
from __future__ import annotations

import hashlib
import re

import yaml

from . import GuardrailResult

from .activity import TICKET_RE


def _norm(s: str) -> str:
    """Whitespace-insensitive form: none around tags, single spaces elsewhere."""
    s = re.sub(r"\s*(<[^>]+>)\s*", r"\1", s.strip())
    return re.sub(r"\s+", " ", s)


def digest(s: str) -> str:
    return hashlib.sha256(_norm(s).encode("utf-8")).hexdigest()


def summary_from_yaml(yaml_text: str) -> str:
    doc = yaml.safe_load(yaml_text)
    return str((doc or {}).get("summary", ""))


def check_message(message_html: str, activity_yaml_text: str) -> GuardrailResult:
    expected = summary_from_yaml(activity_yaml_text)
    if not expected:
        return GuardrailResult.fail("activity YAML has no summary to compare against")
    if digest(message_html) != digest(expected):
        return GuardrailResult.fail("message HTML differs from the step-1 summary (sha256 mismatch)")
    m = TICKET_RE.search(message_html)
    if m:
        return GuardrailResult.fail(f"message contains a ticket number: {m.group(0)!r}")
    return GuardrailResult.ok(f"sha256 {digest(expected)[:12]} matches, no ticket numbers")
