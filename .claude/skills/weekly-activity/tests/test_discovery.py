"""Repo discovery via the Events API."""

START, END = "2026-04-06", "2026-04-10"


def event(day, repo, hour="12:00:00"):
    return {"created_at": f"{day}T{hour}Z", "repo": {"name": repo}}


def test_discover_repos_collects_in_range_org_repos(ga, monkeypatch):
    monkeypatch.setattr(ga.gh, "gh_api", lambda *a, **k: [
        event("2026-04-10", "dragonflyic/gamma"),
        event("2026-04-08", "dragonflyic/alpha"),
        event("2026-04-08", "dragonflyic/alpha"),  # duplicate collapses
    ])
    assert ga.discovery.discover_repos(START, END) == ["dragonflyic/alpha", "dragonflyic/gamma"]


def test_discover_repos_ignores_other_orgs(ga, monkeypatch):
    monkeypatch.setattr(ga.gh, "gh_api", lambda *a, **k: [
        event("2026-04-08", "someoneelse/beta"),
        event("2026-04-08", "dragonflyic/alpha"),
    ])
    assert ga.discovery.discover_repos(START, END) == ["dragonflyic/alpha"]


def test_discover_repos_skips_events_after_the_range(ga, monkeypatch):
    monkeypatch.setattr(ga.gh, "gh_api", lambda *a, **k: [
        event("2026-04-20", "dragonflyic/future"),   # newer than END: skipped, not fatal
        event("2026-04-08", "dragonflyic/alpha"),
    ])
    assert ga.discovery.discover_repos(START, END) == ["dragonflyic/alpha"]


def test_discover_repos_stops_at_the_first_event_before_the_range(ga, monkeypatch):
    # The Events API is newest-first, so the walk short-circuits. Anything after
    # an out-of-range event is never seen, even if it would have matched.
    monkeypatch.setattr(ga.gh, "gh_api", lambda *a, **k: [
        event("2026-04-08", "dragonflyic/alpha"),
        event("2026-04-01", "dragonflyic/old"),
        event("2026-04-09", "dragonflyic/unreachable"),
    ])
    assert ga.discovery.discover_repos(START, END) == ["dragonflyic/alpha"]


def test_discover_repos_queries_the_users_event_feed(ga, monkeypatch):
    seen = {}

    def fake_gh_api(endpoint, params=None, **k):
        seen["endpoint"] = endpoint
        seen["params"] = params
        return []

    monkeypatch.setattr(ga.gh, "gh_api", fake_gh_api)
    assert ga.discovery.discover_repos(START, END) == []
    assert seen["endpoint"] == f"users/{ga.config.GH_USERNAME}/events"
    assert seen["params"] == {"per_page": "100"}
