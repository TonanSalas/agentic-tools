"""main(): argument handling, cache read/write, output selection."""

import json
import os
import time

import pytest

START, END = "2026-04-06", "2026-04-10"


@pytest.fixture
def fake_gather(ga, monkeypatch):
    """Replace the network-bound gather with a counter-backed stub."""
    calls = []

    def _gather(start, end):
        calls.append((start, end))
        return {"generated_at": "2026-04-11T09:00:00-05:00",
                "start": start, "end": end, "repos": ["alpha"],
                "days": {}, "tickets": []}

    monkeypatch.setattr(ga.assemble, "gather_all", _gather)
    return calls


@pytest.fixture
def run_main(ga, monkeypatch, tmp_path):
    def _run(*extra):
        argv = ["gather_activity.py", "--start-date", START, "--end-date", END,
                "--cache-dir", str(tmp_path), *extra]
        monkeypatch.setattr(ga.cli.sys, "argv", argv)
        ga.cli.main()
        return ga.cache.cache_path_for(tmp_path, START, END)
    return _run


def test_main_fetches_and_writes_the_cache_on_a_miss(ga, run_main, fake_gather, capsys):
    cache = run_main("--json")
    capsys.readouterr()
    assert fake_gather == [(START, END)]
    assert json.loads(cache.read_text())["repos"] == ["alpha"]


def test_main_reuses_a_fresh_cache_instead_of_fetching(ga, run_main, fake_gather, capsys):
    # prime the cache, then confirm the second run never calls gather_all
    first = run_main("--json")
    fake_gather.clear()
    first.write_text(json.dumps({"start": START, "end": END, "repos": ["cached"],
                                 "days": {}, "tickets": []}))
    run_main("--json")
    out = capsys.readouterr()
    assert fake_gather == []
    assert '"cached"' in out.out
    assert f"Using cache: {first}" in out.err


def test_no_cache_flag_forces_a_fresh_fetch_and_overwrites(ga, run_main, fake_gather, capsys):
    cache = run_main("--json")
    cache.write_text(json.dumps({"start": START, "end": END, "repos": ["stale"],
                                 "days": {}, "tickets": []}))
    fake_gather.clear()
    run_main("--json", "--no-cache")
    capsys.readouterr()
    assert fake_gather == [(START, END)]
    assert json.loads(cache.read_text())["repos"] == ["alpha"]


def test_main_refetches_when_the_cache_file_is_corrupt(ga, run_main, fake_gather, capsys):
    cache = run_main("--json")
    cache.write_text("{ not json")
    fake_gather.clear()
    run_main("--json")
    capsys.readouterr()
    assert fake_gather == [(START, END)]


def test_main_refetches_when_an_open_week_cache_has_expired(ga, monkeypatch, tmp_path,
                                                            fake_gather, capsys):
    # an end date in the future puts the week "open", so the TTL rule applies
    future_start, future_end = "2999-01-04", "2999-01-08"
    argv = ["gather_activity.py", "--start-date", future_start, "--end-date", future_end,
            "--cache-dir", str(tmp_path), "--json"]
    monkeypatch.setattr(ga.cli.sys, "argv", argv)
    ga.cli.main()
    cache = ga.cache.cache_path_for(tmp_path, future_start, future_end)
    fake_gather.clear()

    ga.cli.main()                       # still inside the TTL: served from cache
    assert fake_gather == []

    old = time.time() - (ga.config.CACHE_TTL_SECONDS + 60)
    os.utime(cache, (old, old))
    ga.cli.main()                       # past the TTL: refetched
    capsys.readouterr()
    assert fake_gather == [(future_start, future_end)]


def test_main_prints_markdown_by_default(ga, run_main, fake_gather, capsys):
    run_main()
    out = capsys.readouterr().out
    assert out.startswith("## Weekly Activity:")


def test_main_prints_json_when_asked(ga, run_main, fake_gather, capsys):
    run_main("--json")
    assert json.loads(capsys.readouterr().out)["start"] == START


def test_main_creates_a_missing_cache_directory(ga, monkeypatch, tmp_path, fake_gather, capsys):
    nested = tmp_path / "does" / "not" / "exist"
    monkeypatch.setattr(ga.cli.sys, "argv", [
        "gather_activity.py", "--start-date", START, "--end-date", END,
        "--cache-dir", str(nested), "--json"])
    ga.cli.main()
    capsys.readouterr()
    assert ga.cache.cache_path_for(nested, START, END).exists()


def test_main_still_prints_when_the_cache_cannot_be_written(ga, monkeypatch, tmp_path,
                                                            fake_gather, capsys):
    monkeypatch.setattr(ga.cli.sys, "argv", [
        "gather_activity.py", "--start-date", START, "--end-date", END,
        "--cache-dir", str(tmp_path), "--json"])
    monkeypatch.setattr(ga.cli.Path, "write_text",
                        lambda self, *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    ga.cli.main()
    out = capsys.readouterr()
    assert json.loads(out.out)["repos"] == ["alpha"]
    assert "failed to write cache" in out.err


@pytest.mark.parametrize("missing", [
    ["--end-date", END],
    ["--start-date", START],
])
def test_main_requires_both_dates(ga, monkeypatch, missing):
    monkeypatch.setattr(ga.cli.sys, "argv", ["gather_activity.py", *missing])
    with pytest.raises(SystemExit):
        ga.cli.main()
