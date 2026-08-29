"""Date handling: UTC->local conversion, range checks, week resolution."""

from datetime import datetime, timedelta

from .config import LOCAL_TZ


def parse_date(iso_str):
    """Convert a UTC ISO timestamp to a local-timezone YYYY-MM-DD date."""
    if not iso_str:
        return None
    try:
        # Handle both "2026-04-04T03:48:35Z" and "2026-04-04T03:48:35+00:00"
        cleaned = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned).astimezone(LOCAL_TZ)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso_str[:10]


def date_in_range(date_str, start, end):
    """Check if a YYYY-MM-DD string falls within [start, end]."""
    if not date_str:
        return False
    return start <= date_str <= end


def resolve_range(keyword: str) -> tuple[str, str]:
    """Resolve 'this-week' / 'last-week' to (start, end) dates, deterministically.

    A week is Monday through today (this-week) or Monday through Sunday of
    the prior week (last-week). Computed in Python so it doesn't depend on
    the caller doing date arithmetic or shelling out to `date`.
    """
    today = datetime.now().date()
    monday_this_week = today - timedelta(days=today.weekday())
    if keyword == "this-week":
        return monday_this_week.isoformat(), today.isoformat()
    if keyword == "last-week":
        monday_last_week = monday_this_week - timedelta(days=7)
        sunday_last_week = monday_this_week - timedelta(days=1)
        return monday_last_week.isoformat(), sunday_last_week.isoformat()
    raise ValueError(f"Unknown range keyword: {keyword!r}")
