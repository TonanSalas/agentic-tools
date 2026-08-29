"""Cache path naming and the closed-week / TTL freshness rules."""

import os
import time


# --- cache -----------------------------------------------------------------

def test_cache_path_for_names_file_by_date_range(ga, tmp_path):
    path = ga.cache.cache_path_for(tmp_path, "2026-04-06", "2026-04-10")
    assert path == tmp_path / "2026-04-06_2026-04-10.json"


def test_cache_is_stale_when_file_absent(ga, tmp_path):
    assert ga.cache.cache_is_fresh(tmp_path / "missing.json", "2020-01-01") is False


def test_closed_week_cache_is_fresh_regardless_of_age(ga, tmp_path):
    path = tmp_path / "old.json"
    path.write_text("{}")
    ancient = time.time() - 10 * 365 * 24 * 3600
    os.utime(path, (ancient, ancient))
    assert ga.cache.cache_is_fresh(path, "2020-01-01") is True


def test_open_week_cache_is_fresh_within_ttl(ga, tmp_path):
    path = tmp_path / "recent.json"
    path.write_text("{}")
    assert ga.cache.cache_is_fresh(path, "2999-01-01") is True


def test_open_week_cache_expires_after_ttl(ga, tmp_path):
    path = tmp_path / "stale.json"
    path.write_text("{}")
    old = time.time() - (ga.config.CACHE_TTL_SECONDS + 60)
    os.utime(path, (old, old))
    assert ga.cache.cache_is_fresh(path, "2999-01-01") is False
