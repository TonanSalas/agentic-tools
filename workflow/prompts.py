"""Prompt builders: one per workflow step. Each prompt names the exact input
file the skill must read and the exact output file it must write, so handoffs
are files in the run directory rather than chat text."""
from __future__ import annotations

from pathlib import Path

HARNESS_NOTE = ("You are running non-interactively inside the weekly-log harness. Do not ask questions; "
                "if something blocks you, stop and report it. ")


def s1(start: str, end: str) -> str:
    return f"/weekly-activity {start}..{end}"


def s2a(hours: str, week_start: str, activity_path: Path | None, out: Path, today: str) -> str:
    act = f" --activity {activity_path}" if activity_path else ""
    return (HARNESS_NOTE + f'/workday-timelogger --plan-only --hours "{hours}" --week-start {week_start}'
            f'{act} --today {today} --out {out}')


def s2b(plan_path: Path, out: Path) -> str:
    return (HARNESS_NOTE + f"/workday-timelogger --enter-only {plan_path} --out {out}\n"
            "Write the JSON result file with a shell heredoc (cat > file <<'EOF' ... EOF). "
            "If Workday needs an interactive SSO login, stop and report 'LOGIN REQUIRED'.")


def s2c() -> str:
    return HARNESS_NOTE + "/workday-timelogger --submit-only"


def s3(message_path: Path, target: str, dry_run: bool) -> str:
    flag = "--dry-run " if dry_run else ""
    return HARNESS_NOTE + f'/teams-messenger {flag}--message-file {message_path} "{target}"'
