"""Append-only JSONL audit log for one weekly-log run.

Every record carries run_id, ts (UTC ISO), kind (step|guardrail|punchout|run),
id and outcome. Step records add model/token/cost fields (see steps.usage_fields);
guardrail records add passed/reason; punch-out records add sentinel_path and
decision. The log is the Stage 4 audit trail: which step produced which output,
at what token count and cost.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

AUDIT_FILENAME = "audit.jsonl"


class Audit:
    def __init__(self, run_dir: Path, run_id: str) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.path = self.run_dir / AUDIT_FILENAME
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, id: str, outcome: str, **fields) -> dict:
        rec = {
            "run_id": self.run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "id": id,
            "outcome": outcome,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return rec


def read_audit(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / AUDIT_FILENAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def first_failure(records: list[dict]) -> dict | None:
    return next((r for r in records if r.get("outcome") == "failed"), None)
