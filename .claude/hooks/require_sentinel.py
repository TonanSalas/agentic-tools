#!/usr/bin/env python3
"""PreToolUse hook: refuse the committing browser click without a human sentinel.

Registered on Bash in .claude/settings.json. Reads the tool input from stdin,
classifies the command, and -- only inside a weekly-log harness run, i.e. when
WEEKLY_LOG_RUN_DIR is set -- exits 2 (block) unless the matching sentinel file
exists in that run directory:

    p1_submit_timesheet   -s=workday click on Submit / Confirm
    p2_send_to_others     -s=teams   click on Send, or Enter / Meta+Enter
                          (only when teams-target.txt names a chat other
                           than the self-chat)

A click by ref (`click e123`) is resolved against every snapshot file written
to .playwright-cli/ in the last 15 minutes (they record lines like
`- button "Send (⌘ Return)" [ref=e123]`); a ref that no recent snapshot names
is blocked in harness mode until a fresh snapshot is taken. So switching from
a role selector to a ref does not evade the check. Outside a
harness run the hook never blocks: interactive skills keep their chat-based
confirmation, and unrelated sessions are unaffected.

Every decision is appended to <run_dir>/hook.log so a blocked attempt is
evidence, not just an absence.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN_DIR_ENV = "WEEKLY_LOG_RUN_DIR"
SELF_CHAT = "Tonan Salas (You)"
P1, P2 = "p1_submit_timesheet", "p2_send_to_others"

_REF_RE = re.compile(r"\bclick\s+['\"]?((?:f\d+)?e\d+)['\"]?")
_SNAPSHOT_GLOB = "page-*.yml"
_SNAPSHOT_WINDOW_S = 15 * 60
UNRESOLVED = "unresolved_ref"


def repo_root() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def ref_names(ref: str, snapshot_dir: Path, now: float | None = None) -> list[str]:
    """Every accessible role+name line recorded for `ref` in snapshots taken
    within the last 15 minutes, newest first. Several browser sessions share
    one snapshot directory and refs repeat across pages, so the caller treats
    a match in ANY recent snapshot as the committing button."""
    import time
    now = now or time.time()
    files = sorted(snapshot_dir.glob(_SNAPSHOT_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
    needle = f"[ref={ref}]"
    out = []
    for f in files:
        if now - f.stat().st_mtime > _SNAPSHOT_WINDOW_S:
            break
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if needle in line:
                out.append(line.strip())
                break
    return out


def classify(command: str, snapshot_dir: Path | None = None) -> str | None:
    """P1 / P2 for a committing click, UNRESOLVED for a ref click that no recent
    snapshot can name (the caller blocks it in harness mode), else None."""
    cmd = command.replace("\n", " ")
    if "-s=workday" in cmd:
        if "click" in cmd:
            targets = _target_texts(cmd, snapshot_dir)
            if targets is None:
                return UNRESOLVED
            if any(_names(t, ("Submit", "Confirm")) for t in targets):
                return P1
    elif "-s=teams" in cmd:
        if "click" in cmd:
            targets = _target_texts(cmd, snapshot_dir)
            if targets is None:
                return UNRESOLVED
            if any(_names(t, ("Send",)) for t in targets):
                return P2
        if re.search(r'press\s+"?(Meta\+|Control\+|Ctrl\+)?(Enter|Return)"?', cmd):
            return P2
    return None


def _names(target: str, names: tuple[str, ...]) -> bool:
    """True if `target` (a selector or a snapshot line) names a button called
    one of `names`: matches `button "Submit"`, `role=button[name="Submit"]`
    and the snapshot form `- button "Submit" [ref=e9]`."""
    alt = "|".join(re.escape(n) for n in names)
    return re.search(rf'(button\s*"|name=")({alt})\b', target) is not None


def _target_texts(cmd: str, snapshot_dir: Path | None) -> list[str] | None:
    """Selector text(s) to inspect: the command itself, or -- for a ref click --
    the snapshot lines that name the ref. None when a ref cannot be resolved."""
    m = _REF_RE.search(cmd)
    if not m or snapshot_dir is None:
        return [cmd]
    names = ref_names(m.group(1), snapshot_dir)
    return names or None


def decide(command: str, run_dir: Path | None, snapshot_dir: Path) -> tuple[int, str]:
    pid = classify(command, snapshot_dir)
    if pid is None:
        return 0, ""
    if run_dir is None:
        return 0, f"{pid}: outside harness run, not enforced"
    if pid == UNRESOLVED:
        return 2, ("BLOCKED by weekly-log guardrail: this click targets an element ref that no recent "
                   "snapshot names, so it cannot be checked against the human sign-off. Take a fresh "
                   "`snapshot` and click the ref it shows, or click by role selector.")
    if pid == P2:
        target_file = run_dir / "teams-target.txt"
        target = target_file.read_text(encoding="utf-8").strip() if target_file.exists() else SELF_CHAT
        if target == SELF_CHAT:
            return 0, f"{pid}: target is the self-chat, no approval needed"
    sentinel = run_dir / f"approved-{pid}.sentinel"
    if sentinel.exists():
        return 0, f"{pid}: sentinel present {sentinel}"
    return 2, (f"BLOCKED by weekly-log guardrail: {pid} requires human approval. "
               f"Missing sentinel: {sentinel}. Stop and report this; do not retry.")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = str((payload.get("tool_input") or {}).get("command", ""))
    run_dir_s = os.environ.get(RUN_DIR_ENV)
    run_dir = Path(run_dir_s) if run_dir_s else None
    code, msg = decide(command, run_dir, repo_root() / ".playwright-cli")
    if run_dir is not None and msg:
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            with (run_dir / "hook.log").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "exit": code,
                                    "command": command[:300], "message": msg}) + "\n")
        except OSError:
            pass
    if code == 2:
        print(msg, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
