"""The `gh` shell-out layer: command construction, pagination fixup, failure modes."""

import json

import pytest


@pytest.fixture
def run_spy(ga, monkeypatch, completed):
    """Capture the argv gather_activity passes to subprocess.run, return a canned result."""
    calls = []

    def _install(stdout="", returncode=0, stderr=""):
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return completed(stdout=stdout, returncode=returncode, stderr=stderr)
        monkeypatch.setattr(ga.gh.subprocess, "run", fake_run)
        return calls

    return _install


# --- gh_api ----------------------------------------------------------------

def test_gh_api_parses_json_payload(ga, run_spy):
    run_spy(stdout='[{"id": 1}]')
    assert ga.gh.gh_api("repos/o/r/commits") == [{"id": 1}]


def test_gh_api_builds_command_with_params_and_pagination(ga, run_spy):
    calls = run_spy(stdout="[]")
    ga.gh.gh_api("repos/o/r/commits", {"author": "someone", "per_page": "100"})
    assert calls[0] == [
        "gh", "api", "repos/o/r/commits", "--method", "GET",
        "-f", "author=someone", "-f", "per_page=100", "--paginate",
    ]


def test_gh_api_omits_paginate_when_disabled(ga, run_spy):
    calls = run_spy(stdout="[]")
    ga.gh.gh_api("repos/o/r/pulls/7/reviews", paginate=False)
    assert "--paginate" not in calls[0]


def test_gh_api_stitches_paginated_json_arrays(ga, run_spy):
    # `gh --paginate` concatenates one array per page; the seam must become a comma
    run_spy(stdout='[{"id": 1}]\n[{"id": 2}]\n[{"id": 3}]')
    assert ga.gh.gh_api("repos/o/r/commits") == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_gh_api_stitches_pages_without_newline_seam(ga, run_spy):
    run_spy(stdout='[{"id": 1}][{"id": 2}]')
    assert ga.gh.gh_api("repos/o/r/commits") == [{"id": 1}, {"id": 2}]


def test_gh_api_returns_empty_list_on_nonzero_exit(ga, run_spy, capsys):
    run_spy(stdout="", returncode=1, stderr="HTTP 404")
    assert ga.gh.gh_api("repos/o/r/commits") == []
    assert "HTTP 404" in capsys.readouterr().err


def test_gh_api_returns_empty_list_on_blank_output(ga, run_spy):
    run_spy(stdout="   \n")
    assert ga.gh.gh_api("repos/o/r/commits") == []


def test_gh_api_returns_empty_list_on_malformed_json(ga, run_spy, capsys):
    run_spy(stdout="not json at all")
    assert ga.gh.gh_api("repos/o/r/commits") == []
    assert "failed to parse JSON" in capsys.readouterr().err


# --- gh_search -------------------------------------------------------------

def test_gh_search_requests_pr_specific_fields(ga, run_spy):
    calls = run_spy(stdout="[]")
    ga.gh.gh_search("org/repo", "pr", ["--search=created:>=2026-04-05"])
    cmd = calls[0]
    assert cmd[:5] == ["gh", "pr", "list", "--repo", "org/repo"]
    assert cmd[cmd.index("--json") + 1] == "number,title,createdAt,mergedAt,body"
    assert f"--author={ga.config.GH_USERNAME}" in cmd
    assert "--search=created:>=2026-04-05" in cmd


def test_gh_search_requests_narrower_fields_for_issues(ga, run_spy):
    calls = run_spy(stdout="[]")
    ga.gh.gh_search("org/repo", "issue", [])
    cmd = calls[0]
    assert cmd[cmd.index("--json") + 1] == "number,title,createdAt"


def test_gh_search_returns_empty_list_on_failure(ga, run_spy, capsys):
    run_spy(stdout="", returncode=1, stderr="no such repo")
    assert ga.gh.gh_search("org/repo", "pr", []) == []
    assert "no such repo" in capsys.readouterr().err


def test_gh_search_returns_empty_list_on_malformed_json(ga, run_spy):
    run_spy(stdout="{{{")
    assert ga.gh.gh_search("org/repo", "pr", []) == []


# --- fetch_item_meta -------------------------------------------------------

def test_fetch_item_meta_reads_a_plain_issue(ga, run_spy):
    run_spy(stdout=json.dumps({
        "title": "Something broke", "state": "CLOSED", "state_reason": "completed",
    }))
    assert ga.gh.fetch_item_meta("org/repo", 101) == {
        "title": "Something broke",
        "state": "closed",          # normalised to lowercase
        "state_reason": "completed",
        "is_pr": False,
        "merged": None,             # not applicable to issues
    }


def test_fetch_item_meta_marks_merged_pull_requests(ga, run_spy):
    run_spy(stdout=json.dumps({
        "title": "feat: add widget", "state": "closed",
        "pull_request": {"merged_at": "2026-04-09T15:00:00Z"},
    }))
    meta = ga.gh.fetch_item_meta("org/repo", 55)
    assert (meta["is_pr"], meta["merged"]) == (True, True)


def test_fetch_item_meta_marks_unmerged_pull_requests(ga, run_spy):
    run_spy(stdout=json.dumps({
        "title": "wip", "state": "open", "pull_request": {"merged_at": None},
    }))
    meta = ga.gh.fetch_item_meta("org/repo", 56)
    assert (meta["is_pr"], meta["merged"]) == (True, False)


def test_fetch_item_meta_does_not_strip_prefixes_itself(ga, run_spy):
    # callers are responsible for stripping; keep the raw title here
    run_spy(stdout=json.dumps({"title": "feat: add widget", "state": "open"}))
    assert ga.gh.fetch_item_meta("org/repo", 55)["title"] == "feat: add widget"


@pytest.mark.parametrize("stdout,returncode", [
    ("", 1),              # gh failed (e.g. ticket lives in another org)
    ("", 0),              # empty body
    ("not json", 0),      # unparseable body
])
def test_fetch_item_meta_falls_back_to_safe_defaults(ga, run_spy, stdout, returncode):
    run_spy(stdout=stdout, returncode=returncode)
    assert ga.gh.fetch_item_meta("org/repo", 999) == {
        "title": "(unknown #999)",
        "state": "unknown",
        "state_reason": None,
        "is_pr": False,
        "merged": None,
    }


def test_fetch_item_title_returns_just_the_title(ga, run_spy):
    run_spy(stdout=json.dumps({"title": "Something broke", "state": "open"}))
    assert ga.gh.fetch_item_title("org/repo", 101) == "Something broke"
