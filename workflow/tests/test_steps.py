import json
from pathlib import Path

from workflow.steps import StepResult, parse_stream, usage_fields

FIX = Path(__file__).parent / "fixtures" / "stream_ok.jsonl"


def test_parse_real_fixture(tmp_path: Path):
    r = parse_stream(FIX.read_text().splitlines(), tmp_path / "raw.jsonl")
    assert isinstance(r, StepResult)
    assert "fixture-ok" in r.text
    assert r.total_cost_usd > 0
    assert r.input_tokens >= 0 and r.output_tokens > 0
    assert "claude-haiku-4-5-20251001" in r.model_usage
    assert r.session_id
    assert r.duration_ms > 0
    assert r.num_turns >= 1
    assert r.is_error is False
    assert any("echo fixture-ok" in c["input"].get("command", "") for c in r.tool_calls)
    assert r.blocked_calls == []


def _events(tool_result_error: bool, text: str):
    return [
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "npx x click e1"}}]}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": tool_result_error, "content": text}]}}),
        json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "done",
                    "duration_ms": 10, "num_turns": 1, "session_id": "s", "total_cost_usd": 0.01,
                    "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3,
                              "cache_creation_input_tokens": 4},
                    "modelUsage": {"m": {"inputTokens": 1, "outputTokens": 2, "costUSD": 0.01}}}),
    ]


def test_blocked_sentinel_call_is_separated(tmp_path: Path):
    r = parse_stream(_events(True, "BLOCKED by weekly-log guardrail: missing sentinel"), tmp_path / "r.jsonl")
    assert r.tool_calls == []
    assert len(r.blocked_calls) == 1 and "sentinel" in r.blocked_calls[0]["error"]


def test_plain_error_is_not_blocked(tmp_path: Path):
    r = parse_stream(_events(True, "command not found"), tmp_path / "r.jsonl")
    assert r.tool_calls == [] and r.blocked_calls == []
    assert r.failed_calls and r.failed_calls[0]["error"] == "command not found"


def test_usage_fields(tmp_path: Path):
    r = parse_stream(_events(False, "ok"), tmp_path / "r.jsonl")
    f = usage_fields(r)
    assert f["model"] == "m" and f["cost_usd"] == 0.01
    assert f["input_tokens"] == 1 and f["output_tokens"] == 2
    assert f["cache_read_tokens"] == 3 and f["cache_creation_tokens"] == 4


def test_missing_result_event_is_error(tmp_path: Path):
    r = parse_stream(_events(False, "ok")[:2], tmp_path / "r.jsonl")
    assert r.is_error is True
