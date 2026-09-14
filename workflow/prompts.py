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
            "Write the JSON result file with a shell heredoc (cat > file <<'EOF' ... EOF).\n"
            "Workday shows its 'Sign In to Your Account' page first: click the 'Single Sign-on' link once and "
            "wait ~10s; the persisted Microsoft session normally completes the login by itself.\n"
            "CRITICAL navigation rules (violating these caused false 'LOGIN REQUIRED' failures in earlier runs):\n"
            "- NEVER open a deep-link task URL like /d/task/2998$10895.htmld. Reach Enter My Time only by clicking "
            "the Search Workday combobox and its result. Use ONLY the home URL "
            "https://wd5.myworkday.com/improving/d/home.htmld to (re)authenticate.\n"
            "- The Menu/Shortcuts side dialog after login is off-screen and inert; do NOT fight it (no Escape/Close "
            "loops). Take a fresh snapshot and click the Search combobox by its current ref.\n"
            "- Write {\"error\": \"LOGIN REQUIRED\"} and stop ONLY if the HOME url itself still shows a "
            "username/password/MFA field after you click Single Sign-on and wait. A Microsoft sign-in page reached "
            "by deep-linking is NOT a real login failure; go back to the home URL instead.")


def s2c() -> str:
    return HARNESS_NOTE + "/workday-timelogger --submit-only"


def s3(message_path: Path, target: str, dry_run: bool) -> str:
    flag = "--dry-run " if dry_run else ""
    return HARNESS_NOTE + f'/teams-messenger {flag}--message-file {message_path} "{target}"'
