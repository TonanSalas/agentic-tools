"""Markdown rendering of an already-gathered payload."""

import pytest


def ticket(number, repo="alpha", title="add widget", is_pr=True, merged=True, days=None):
    return {"repo": repo, "number": number, "title": title, "state": "closed",
            "state_reason": None, "is_pr": is_pr, "merged": merged,
            "days": days or ["2026-04-06"], "sources": ["authored-pr"]}


def item(number, repo="alpha", title="add widget", sources=("authored-pr",)):
    return {"repo": repo, "number": number, "title": title, "state": "closed",
            "state_reason": None, "is_pr": True, "merged": True,
            "sources": list(sources)}


def payload(**overrides):
    data = {
        "generated_at": "2026-04-11T09:00:00-05:00",
        "start": "2026-04-06",
        "end": "2026-04-10",
        "repos": ["alpha"],
        "days": {"2026-04-06": [item(55)]},
        "tickets": [ticket(55)],
    }
    data.update(overrides)
    return data


def test_render_reports_no_activity_when_no_repos_were_active(ga):
    out = ga.render.render_markdown(payload(repos=[], days={}, tickets=[]))
    assert out == f"No activity found for {ga.config.GH_USERNAME} between 2026-04-06 and 2026-04-10."


def test_render_writes_a_dated_heading(ga):
    out = ga.render.render_markdown(payload())
    assert out.splitlines()[0] == (
        "## Weekly Activity: Monday 2026-04-06 - Friday 2026-04-10, 2026"
    )


def test_render_emits_one_row_per_calendar_day_in_the_range(ga):
    out = ga.render.render_markdown(payload())
    labels = ["Mon 04/06", "Tue 04/07", "Wed 04/08", "Thu 04/09", "Fri 04/10"]
    for label in labels:
        assert f"| {label} |" in out


def test_render_marks_days_without_activity(ga):
    out = ga.render.render_markdown(payload())
    assert "| Tue 04/07 | No activity | |" in out


def test_render_omits_the_repo_name_for_a_single_repo_week(ga):
    out = ga.render.render_markdown(payload())
    assert "| Mon 04/06 | #55: add widget | authored-pr |" in out


def test_render_qualifies_tickets_with_the_repo_when_several_are_active(ga):
    out = ga.render.render_markdown(payload(
        repos=["alpha", "beta"],
        days={"2026-04-06": [item(55), item(9, repo="beta", title="beta thing")]},
    ))
    assert "| Mon 04/06 | alpha#55: add widget, beta#9: beta thing |" in out


def test_render_shows_only_the_first_source_per_item(ga):
    out = ga.render.render_markdown(payload(
        days={"2026-04-06": [item(55, sources=("authored-pr", "commits"))]},
    ))
    assert "| authored-pr |" in out
    assert "commits" not in out


def test_render_tolerates_an_item_with_no_sources(ga):
    out = ga.render.render_markdown(payload(days={"2026-04-06": [item(55, sources=())]}))
    assert "| Mon 04/06 | #55: add widget |  |" in out


def test_render_summarises_repos_and_ticket_totals(ga):
    out = ga.render.render_markdown(payload(
        repos=["alpha", "beta"],
        tickets=[ticket(55), ticket(9, repo="beta", is_pr=False, merged=None)],
    ))
    assert "- Repos: alpha, beta" in out
    assert "- Total Tickets Touched: 2" in out


def test_render_counts_merged_and_open_pull_requests(ga):
    out = ga.render.render_markdown(payload(tickets=[
        ticket(55, merged=True),
        ticket(56, merged=False),
        ticket(57, merged=False),
        ticket(9, is_pr=False, merged=None),   # issues are excluded from PR counts
    ]))
    assert "- Total PRs: 3 (1 merged, 2 open)" in out


def test_render_ignores_activity_days_outside_the_range(ga):
    out = ga.render.render_markdown(payload(days={
        "2026-04-06": [item(55)],
        "2026-04-25": [item(88, title="stray")],
    }))
    assert "stray" not in out
