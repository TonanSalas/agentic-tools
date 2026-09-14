"""Run one workflow step as a headless Claude Code turn and parse its stream.

`run_step` shells out to `claude -p ... --output-format stream-json`, saves the
raw stream in the run directory, and returns a StepResult carrying the final
text, the tool calls that ran, the ones the sentinel hook blocked, and the
turn's model/token/cost figures from the `result` event. Those figures are the
audit trail's per-step cost data.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_DIR_ENV = "WEEKLY_LOG_RUN_DIR"
# The hook prefixes every block with this exact phrase. Matching the word
# "sentinel" alone was wrong: the hook's own script path (require_sentinel.py)
# echoes into the error text, so a mere unresolved-ref nudge looked like a denial.
BLOCK_MARKER = "BLOCKED by weekly-log guardrail"
DENIAL_MARKER = "requires human approval"        # a real punch-out denial, vs a retryable nudge


@dataclass
class StepResult:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)      # completed without error
    failed_calls: list[dict] = field(default_factory=list)    # tool_result is_error, not a hook block
    blocked_calls: list[dict] = field(default_factory=list)   # refused by the sentinel hook (denial or nudge)
    model_usage: dict = field(default_factory=dict)
    total_cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    duration_ms: int = 0
    num_turns: int = 0
    session_id: str = ""
    is_error: bool = True
    error: str = ""
    raw_path: Path | None = None

    @property
    def models(self) -> list[str]:
        return sorted(self.model_usage)

    @property
    def denied_calls(self) -> list[dict]:
        """Blocks that were real punch-out denials (missing sentinel), not the
        retryable 'take a fresh snapshot' nudge for an unresolvable ref."""
        return [c for c in self.blocked_calls if DENIAL_MARKER in c.get("error", "")]

    def committed(self, *needles: str) -> bool:
        """Did any SUCCESSFUL tool call click a committing button (by any of
        `needles`, e.g. 'Send' or 'Submit')? A blocked attempt that the model
        then retried successfully counts as committed."""
        for c in self.tool_calls:
            cmd = c["input"].get("command", "")
            if "click" in cmd and any(n in cmd for n in needles):
                return True
        return False


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return str(content)


def parse_stream(lines: Iterable[str], raw_path: Path) -> StepResult:
    r = StepResult(raw_path=raw_path)
    attempted: dict[str, dict] = {}
    saw_result = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "assistant":
            for b in ev.get("message", {}).get("content", []) or []:
                if b.get("type") == "tool_use":
                    attempted[b.get("id", "")] = {"name": b.get("name", "tool"), "input": b.get("input", {})}
        elif t == "user":
            content = ev.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            for b in content:
                if b.get("type") != "tool_result":
                    continue
                call = dict(attempted.get(b.get("tool_use_id", ""), {"name": "tool", "input": {}}))
                if b.get("is_error"):
                    call["error"] = _result_text(b.get("content"))
                    (r.blocked_calls if BLOCK_MARKER in call["error"] else r.failed_calls).append(call)
                else:
                    r.tool_calls.append(call)
        elif t == "result":
            saw_result = True
            r.text = ev.get("result", "") or ""
            r.is_error = bool(ev.get("is_error", False))
            r.error = "" if not r.is_error else (ev.get("subtype") or "error")
            r.duration_ms = int(ev.get("duration_ms", 0) or 0)
            r.num_turns = int(ev.get("num_turns", 0) or 0)
            r.session_id = ev.get("session_id", "") or ""
            r.total_cost_usd = float(ev.get("total_cost_usd", 0.0) or 0.0)
            u = ev.get("usage", {}) or {}
            r.input_tokens = int(u.get("input_tokens", 0) or 0)
            r.output_tokens = int(u.get("output_tokens", 0) or 0)
            r.cache_read_tokens = int(u.get("cache_read_input_tokens", 0) or 0)
            r.cache_creation_tokens = int(u.get("cache_creation_input_tokens", 0) or 0)
            r.model_usage = ev.get("modelUsage", {}) or {}
    if not saw_result:
        r.is_error = True
        r.error = r.error or "no result event in stream (turn did not finish)"
    return r


def usage_fields(r: StepResult) -> dict:
    return {
        "model": ",".join(r.models),
        "model_usage": r.model_usage,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "cache_read_tokens": r.cache_read_tokens,
        "cache_creation_tokens": r.cache_creation_tokens,
        "cost_usd": r.total_cost_usd,
        "duration_ms": r.duration_ms,
        "num_turns": r.num_turns,
        "session_id": r.session_id,
        "tool_calls": len(r.tool_calls),
        "blocked_calls": [c["input"].get("command", "") for c in r.blocked_calls],
        "raw_path": str(r.raw_path) if r.raw_path else None,
    }


def run_step(step_id: str, prompt: str, run_dir: Path, model: str,
             extra_env: dict | None = None, timeout: int = 1200) -> StepResult:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_path = run_dir / f"{step_id}.stream.jsonl"
    (run_dir / f"{step_id}.prompt.txt").write_text(prompt, encoding="utf-8")
    env = {**os.environ, **(extra_env or {}), RUN_DIR_ENV: str(run_dir.resolve())}
    started = time.time()
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raw_path.write_text((e.stdout or "") if isinstance(e.stdout, str) else "", encoding="utf-8")
        r = parse_stream(raw_path.read_text(encoding="utf-8").splitlines(), raw_path)
        r.is_error, r.error = True, f"timeout after {timeout}s"
        r.duration_ms = int((time.time() - started) * 1000)
        return r
    raw_path.write_text(proc.stdout, encoding="utf-8")
    r = parse_stream(proc.stdout.splitlines(), raw_path)
    if proc.returncode != 0 and not r.text:
        r.is_error = True
        r.error = f"claude exited {proc.returncode}: {proc.stderr[-800:]}"
    if not r.duration_ms:
        r.duration_ms = int((time.time() - started) * 1000)
    return r
