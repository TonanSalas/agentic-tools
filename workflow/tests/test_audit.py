import json
from pathlib import Path

from workflow.audit import Audit, first_failure, read_audit


def test_record_writes_required_keys(tmp_path: Path):
    a = Audit(tmp_path, "run-1")
    rec = a.record("step", "s1_activity", "success", model="m", cost_usd=0.1)
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert loaded == rec
    for k in ("run_id", "ts", "kind", "id", "outcome", "model", "cost_usd"):
        assert k in loaded
    assert loaded["run_id"] == "run-1" and loaded["outcome"] == "success"


def test_read_returns_in_order(tmp_path: Path):
    a = Audit(tmp_path, "r")
    a.record("step", "s1_activity", "success")
    a.record("guardrail", "g1_activity_check", "passed")
    assert [r["id"] for r in read_audit(tmp_path)] == ["s1_activity", "g1_activity_check"]


def test_first_failure(tmp_path: Path):
    a = Audit(tmp_path, "r")
    a.record("step", "s1_activity", "success")
    assert first_failure(read_audit(tmp_path)) is None
    a.record("guardrail", "g1_activity_check", "failed", reason="bad")
    a.record("guardrail", "g2_plan_check", "failed", reason="later")
    assert first_failure(read_audit(tmp_path))["id"] == "g1_activity_check"


def test_read_missing_file_is_empty(tmp_path: Path):
    assert read_audit(tmp_path) == []
