from datetime import date

import pytest
from plan_entries import MAX_COMMENT, build_plan, parse_hours

WEEK = date(2026, 9, 14)
TODAY = date(2026, 9, 20)


def act(items_by_date):
    return {"days": [{"date": d, "items": [{"ref": r, "title": t} for r, t in items]}
                     for d, items in items_by_date.items()]}


def test_parse_hours_basic():
    assert parse_hours("Mon 11, Tue 8, Fri 5") == {"Mon": 11.0, "Tue": 8.0, "Fri": 5.0}


def test_parse_hours_accepts_full_day_names_and_case():
    assert parse_hours("monday 8, Tuesday 7.5") == {"Mon": 8.0, "Tue": 7.5}


def test_parse_hours_rejects_over_11():
    with pytest.raises(ValueError):
        parse_hours("Mon 12")


def test_parse_hours_rejects_garbage():
    with pytest.raises(ValueError):
        parse_hours("eight hours")


def test_split_over_eight():
    plan = build_plan({"Mon": 11}, WEEK,
                      act({"2026-09-14": [("a#1", "One"), ("a#2", "Two"), ("a#3", "Three")]}), TODAY)
    reg, extra = plan["entries"]
    assert (reg["entry"], reg["hours"]) == ("Reg", 8)
    assert (extra["entry"], extra["hours"]) == ("Extra", 3)
    assert set(reg["tickets"]) | set(extra["tickets"]) == {"a#1", "a#2", "a#3"}
    assert reg["tickets"] and extra["tickets"]


def test_single_ticket_used_in_both_entries():
    plan = build_plan({"Mon": 9}, WEEK, act({"2026-09-14": [("a#1", "One")]}), TODAY)
    assert [e["tickets"] for e in plan["entries"]] == [["a#1"], ["a#1"]]


def test_unknown_tickets_dropped():
    plan = build_plan({"Mon": 8}, WEEK,
                      act({"2026-09-14": [("a#1", "One"), ("b#9", "(unknown #9)")]}), TODAY)
    assert plan["entries"][0]["tickets"] == ["a#1"]
    assert [i["ref"] for i in plan["issues"]] == ["a#1"]


def test_future_day_gets_placeholder():
    plan = build_plan({"Wed": 8}, WEEK, None, date(2026, 9, 13))
    assert plan["entries"][0]["comment"] == "Activity placeholder"
    assert plan["entries"][0]["tickets"] == []


def test_no_activity_on_past_day_gets_placeholder():
    plan = build_plan({"Mon": 8}, WEEK, act({"2026-09-14": []}), TODAY)
    assert plan["entries"][0]["comment"] == "Activity placeholder"


def test_comment_format_and_overflow():
    items = [(f"a#{i}", "x" * 40) for i in range(1, 12)]
    plan = build_plan({"Mon": 8}, WEEK, act({"2026-09-14": items}), TODAY)
    c = plan["entries"][0]["comment"]
    assert len(c) <= MAX_COMMENT
    assert c.startswith("a#1, a#2")
    short = build_plan({"Mon": 8}, WEEK, act({"2026-09-14": [("a#1", "Fix auth")]}), TODAY)
    assert short["entries"][0]["comment"] == "a#1: Fix auth"


def test_dates_follow_week_start_and_order():
    plan = build_plan({"Tue": 8, "Mon": 8}, WEEK, None, TODAY)
    assert [e["date"] for e in plan["entries"]] == ["2026-09-14", "2026-09-15"]


def test_fractional_hours_preserved():
    plan = build_plan({"Fri": 7.5}, WEEK, None, TODAY)
    assert plan["entries"][0]["hours"] == 7.5
