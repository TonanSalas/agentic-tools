#!/usr/bin/env python3
"""Delete unsubmitted Dragonfly time entries from the displayed Workday week.

Test runs enter hours into Workday but, by policy, never submit them (a
submitted week cannot be deleted). This removes the entries a test run left
behind. It only ever deletes "Dragonfly: Team extended- Python development"
project-time blocks; it never touches Holiday or PTO blocks.

Preconditions (the harness / operator sets these up once):
  * the `-s=workday` Playwright session is logged in, on "Enter My Time",
    and showing the target week (the same session the harness used).

    python3 workflow/cleanup_workday.py                 # clean the displayed week
    python3 workflow/cleanup_workday.py --dry-run        # just report what it would delete
    python3 workflow/cleanup_workday.py --max 10         # safety cap on deletions

Discovered delete flow (validated by hand on 2026-09-14, Sep 13–19 week):
  1. On the weekly grid, each entry is a link whose name starts
     "Dragonfly: Team extended- Python development ... Project > Time Entry".
  2. Clicking it opens an entry dialog with a "Delete" button.
  3. Clicking "Delete" opens a "Delete Time Block" confirmation dialog with "OK".
  4. Clicking "OK" removes the block; the weekly Project Time total drops by its hours.
Refs are re-read from a fresh snapshot every iteration because every delete
reflows the grid and invalidates them.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time

SESSION = "workday"
ENTRY_LINK_RE = re.compile(r'link "(Dragonfly: Team extended[^"]*Time Entry)" \[ref=(f?\d*e\d+)\]')
DELETE_BTN_RE = re.compile(r'button "Delete" \[ref=(f?\d*e\d+)\]')
OK_UNDER_DELETE_RE = re.compile(r'Delete Time Block.*?button "OK" \[ref=(f?\d*e\d+)\]', re.S)


def _cli(*args: str, timeout: int = 60) -> str:
    return subprocess.run(["npx", "@playwright/cli@latest", f"-s={SESSION}", *args],
                          capture_output=True, text=True, timeout=timeout).stdout


def _snapshot() -> str:
    _cli("snapshot")
    import glob, os
    files = sorted(glob.glob(".playwright-cli/page-*.yml"), key=os.path.getmtime)
    return open(files[-1], encoding="utf-8", errors="replace").read() if files else ""


def _first_entry_ref(snap: str) -> str | None:
    m = ENTRY_LINK_RE.search(snap)
    return m.group(2) if m else None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max", type=int, default=14, help="max deletions (safety cap)")
    a = p.parse_args(argv)

    snap = _snapshot()
    if "Enter My Time" not in snap and "Enter Time" not in snap:
        print("Not on the Enter My Time weekly view — navigate there in the -s=workday session first.", file=sys.stderr)
        return 2
    n = len(ENTRY_LINK_RE.findall(snap))
    print(f"Found {n} Dragonfly project-time entry(ies) on the displayed week.")
    if a.dry_run:
        for name, ref in ENTRY_LINK_RE.findall(snap):
            print(f"  would delete: {name}  [{ref}]")
        return 0

    deleted = 0
    while deleted < a.max:
        snap = _snapshot()
        ref = _first_entry_ref(snap)
        if not ref:
            break
        _cli("click", ref); time.sleep(2)
        snap = _snapshot()
        dm = DELETE_BTN_RE.search(snap)
        if not dm:
            print("  no Delete button in the entry dialog — stopping.", file=sys.stderr)
            break
        _cli("click", dm.group(1)); time.sleep(2)
        snap = _snapshot()
        okm = OK_UNDER_DELETE_RE.search(snap)
        if not okm:
            print("  no 'Delete Time Block' confirmation — stopping.", file=sys.stderr)
            break
        _cli("click", okm.group(1)); time.sleep(2)
        deleted += 1
        print(f"  deleted entry {deleted}")

    remaining = len(ENTRY_LINK_RE.findall(_snapshot()))
    print(f"Done. Deleted {deleted}; {remaining} Dragonfly entry(ies) remain.")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
