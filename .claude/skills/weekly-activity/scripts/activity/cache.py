"""On-disk cache of gathered payloads, keyed by date range."""

import time
from datetime import datetime
from pathlib import Path

from .config import CACHE_TTL_SECONDS, LOCAL_TZ


def cache_path_for(cache_dir, start, end):
    return Path(cache_dir) / f"{start}_{end}.json"


def cache_is_fresh(path, end_date):
    """Closed weeks (end < today) cache forever; current/future weeks expire after CACHE_TTL_SECONDS."""
    if not path.exists():
        return False
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    if end_date < today:
        return True
    return (time.time() - path.stat().st_mtime) < CACHE_TTL_SECONDS
