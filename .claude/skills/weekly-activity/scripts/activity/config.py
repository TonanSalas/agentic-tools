"""Static configuration: org/user identity, timezone, cache policy."""

from datetime import timedelta, timezone
from pathlib import Path

ORG = "dragonflyic"
GH_USERNAME = "tonansalas-dragonfly"
GIT_AUTHOR = "tonansalas"
LOCAL_TZ = timezone(timedelta(hours=-5))  # CDT (US Central Daylight)

# scripts/activity/config.py -> scripts/activity -> scripts -> <skill root>
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"
CACHE_TTL_SECONDS = 3600  # 1h for current/future weeks; closed weeks cached forever

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
