#!/usr/bin/env python3
"""Entry point for the weekly-activity gatherer.

The implementation lives in the `activity` package alongside this file; this
shim keeps the documented invocation path (`scripts/gather_activity.py`)
stable for SKILL.md and every other caller.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from activity.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
