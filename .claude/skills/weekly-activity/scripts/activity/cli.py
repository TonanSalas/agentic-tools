"""Command-line entry point: argument parsing, cache read/write, JSON output."""

import argparse
import json
import sys
from pathlib import Path

from . import assemble, cache, dates
from .config import DEFAULT_CACHE_DIR


def main():
    parser = argparse.ArgumentParser(description="Gather GitHub activity")
    parser.add_argument("--range", choices=["this-week", "last-week"],
                        help="Resolve dates deterministically instead of passing them explicitly")
    parser.add_argument("--start-date", help="Start date YYYY-MM-DD (ignored if --range is set)")
    parser.add_argument("--end-date", help="End date YYYY-MM-DD (ignored if --range is set)")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR),
                        help="Cache directory (default: <skill>/cache/)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Force a fresh fetch and overwrite any cached result")
    args = parser.parse_args()

    if args.range:
        start, end = dates.resolve_range(args.range)
    elif args.start_date and args.end_date:
        start, end = args.start_date, args.end_date
    else:
        parser.error("either --range or both --start-date/--end-date are required")
    cache_dir = Path(args.cache_dir)
    cache_path = cache.cache_path_for(cache_dir, start, end)

    data = None
    if not args.no_cache and cache.cache_is_fresh(cache_path, end):
        try:
            data = json.loads(cache_path.read_text())
            print(f"Using cache: {cache_path}", file=sys.stderr)
        except (json.JSONDecodeError, OSError):
            data = None

    if data is None:
        data = assemble.gather_all(start, end)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, indent=2))
        except OSError as e:
            print(f"Warning: failed to write cache: {e}", file=sys.stderr)

    print(json.dumps(data, indent=2))
