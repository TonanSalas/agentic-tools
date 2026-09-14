"""Guardrails run by the harness between workflow steps.

Each check is a pure function returning GuardrailResult(passed, reason). None
of them lives inside a skill: they inspect the file one step wrote before the
next step is allowed to consume it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailResult:
    passed: bool
    reason: str

    @staticmethod
    def ok(reason: str = "ok") -> "GuardrailResult":
        return GuardrailResult(True, reason)

    @staticmethod
    def fail(reason: str) -> "GuardrailResult":
        return GuardrailResult(False, reason)
