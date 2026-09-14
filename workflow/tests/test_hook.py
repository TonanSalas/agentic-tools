import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "require_sentinel.py"

spec = importlib.util.spec_from_file_location("require_sentinel", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def snapshot_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".playwright-cli"
    d.mkdir()
    (d / "page-2026-01-01T00-00-00-000Z.yml").write_text(
        '- button "Chat" [ref=e5]\n- button "Send (⌘ Return)" [ref=e1758]\n- button "Submit" [ref=e900]\n')
    return d


def test_classify_role_selectors(tmp_path):
    sd = snapshot_dir(tmp_path)
    assert hook.classify("npx @playwright/cli@latest -s=workday click 'role=button[name=\"Submit\"]'", sd) == hook.P1
    assert hook.classify("npx @playwright/cli@latest -s=workday click 'button \"Confirm\"'", sd) == hook.P1
    assert hook.classify("npx @playwright/cli@latest -s=teams click 'role=button[name=\"Send (⌘ Return)\"]'", sd) == hook.P2
    assert hook.classify("npx @playwright/cli@latest -s=teams press \"Meta+Enter\"", sd) == hook.P2
    assert hook.classify("npx @playwright/cli@latest -s=teams press \"Meta+v\"", sd) is None
    assert hook.classify("npx @playwright/cli@latest -s=workday click e5", sd) is None
    assert hook.classify("npx @playwright/cli@latest -s=workday mousedown", sd) is None


def test_classify_resolves_ref_from_snapshot(tmp_path):
    sd = snapshot_dir(tmp_path)
    assert hook.classify("npx @playwright/cli@latest -s=teams click 'e1758'", sd) == hook.P2
    assert hook.classify("npx @playwright/cli@latest -s=workday click e900", sd) == hook.P1
    assert hook.classify("npx @playwright/cli@latest -s=teams click e5", sd) is None


def test_decide_outside_harness_never_blocks(tmp_path):
    sd = snapshot_dir(tmp_path)
    code, _ = hook.decide("npx @playwright/cli@latest -s=workday click 'role=button[name=\"Submit\"]'", None, sd)
    assert code == 0


def test_decide_blocks_without_sentinel_and_allows_with(tmp_path):
    sd = snapshot_dir(tmp_path)
    run = tmp_path / "run"; run.mkdir()
    cmd = "npx @playwright/cli@latest -s=workday click e900"
    code, msg = hook.decide(cmd, run, sd)
    assert code == 2 and "p1_submit_timesheet" in msg and "approved-p1_submit_timesheet.sentinel" in msg
    (run / "approved-p1_submit_timesheet.sentinel").write_text("ok")
    assert hook.decide(cmd, run, sd)[0] == 0


def test_teams_self_chat_needs_no_sentinel_but_others_do(tmp_path):
    sd = snapshot_dir(tmp_path)
    run = tmp_path / "run"; run.mkdir()
    cmd = "npx @playwright/cli@latest -s=teams click 'role=button[name=\"Send (⌘ Return)\"]'"
    assert hook.decide(cmd, run, sd)[0] == 0
    (run / "teams-target.txt").write_text("Dragonfly Team")
    assert hook.decide(cmd, run, sd)[0] == 2
    (run / "approved-p2_send_to_others.sentinel").write_text("ok")
    assert hook.decide(cmd, run, sd)[0] == 0


def _run_hook(command: str, env_extra: dict, cwd: Path) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(cwd), **env_extra}
    env.pop(hook.RUN_DIR_ENV, None) if hook.RUN_DIR_ENV not in env_extra else None
    return subprocess.run([sys.executable, str(HOOK)], input=payload, text=True, capture_output=True, env=env)


def test_process_exit_codes_and_log(tmp_path):
    snapshot_dir(tmp_path)
    run = tmp_path / "run"
    cmd = "npx @playwright/cli@latest -s=workday click 'role=button[name=\"Submit\"]'"
    assert _run_hook(cmd, {}, tmp_path).returncode == 0
    p = _run_hook(cmd, {hook.RUN_DIR_ENV: str(run)}, tmp_path)
    assert p.returncode == 2 and "BLOCKED" in p.stderr
    log = (run / "hook.log").read_text().splitlines()
    assert len(log) == 1 and json.loads(log[0])["exit"] == 2
    assert _run_hook("ls", {hook.RUN_DIR_ENV: str(run)}, tmp_path).returncode == 0


def test_invalid_stdin_is_allowed(tmp_path):
    p = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True, capture_output=True)
    assert p.returncode == 0
