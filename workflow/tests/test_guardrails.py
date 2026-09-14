import json
from datetime import date
from pathlib import Path

import yaml

from workflow.guardrails.activity import check_activity, refs_in_cache
from workflow.guardrails.adversarial import parse_claims
from workflow.guardrails.entry import check_entry
from workflow.guardrails.message import check_message
from workflow.guardrails.plan import check_plan

CACHE = {"start": "2026-09-14", "end": "2026-09-15",
         "tickets": [{"repo": "ao", "number": 1, "title": "One", "state": "closed", "merged": True, "days": ["2026-09-14"]}],
         "days": {"2026-09-14": [{"repo": "ao", "number": 1, "title": "One"}]}}

SUMMARY = ("<html><b>TEC Weekly Status Report – Dragonfly</b><br><b>Project:</b> Dragonfly<br>"
           "<b>Date:</b> September 15, 2026<br><b>Status:</b> 🟢<br><br><b>Summary</b><br>Did one thing.<br>"
           "<b>Accomplished</b><ul><li>One</li></ul><b>Planned Activities</b><ul></ul><b>Risks</b><br>"
           "No risks identified at the moment.</html>")


def activity_doc(**over):
    doc = {"range": {"start": "2026-09-14", "end": "2026-09-15"},
           "days": [{"date": "2026-09-14", "items": [{"ref": "ao#1", "title": "One"}], "summary": "x"},
                    {"date": "2026-09-15", "items": [], "summary": "quiet"}],
           "summary": SUMMARY}
    doc.update(over)
    return doc


def dump(doc):
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


# ---- g1 -------------------------------------------------------------------

def test_refs_in_cache():
    assert refs_in_cache(CACHE) == {"ao#1"}


def test_activity_passes():
    assert check_activity(dump(activity_doc()), "2026-09-14", "2026-09-15", CACHE).passed


def test_activity_rejects_bad_yaml():
    assert not check_activity(": : :\n  - [", "2026-09-14", "2026-09-15", CACHE).passed


def test_activity_rejects_wrong_range():
    r = check_activity(dump(activity_doc(range={"start": "2026-09-07", "end": "2026-09-11"})), "2026-09-14", "2026-09-15", CACHE)
    assert not r.passed and "range" in r.reason


def test_activity_rejects_missing_day():
    doc = activity_doc(); doc["days"].pop()
    r = check_activity(dump(doc), "2026-09-14", "2026-09-15", CACHE)
    assert not r.passed and "days" in r.reason


def test_activity_rejects_fabricated_ref():
    doc = activity_doc(); doc["days"][1]["items"] = [{"ref": "ao#999", "title": "Made up"}]
    r = check_activity(dump(doc), "2026-09-14", "2026-09-15", CACHE)
    assert not r.passed and "ao#999" in r.reason


def test_activity_rejects_dropped_ref():
    doc = activity_doc(); doc["days"][0]["items"] = []
    r = check_activity(dump(doc), "2026-09-14", "2026-09-15", CACHE)
    assert not r.passed and "dropped" in r.reason


def test_activity_rejects_ticket_number_in_summary():
    r = check_activity(dump(activity_doc(summary=SUMMARY.replace("<li>One</li>", "<li>ao#1 One</li>"))), "2026-09-14", "2026-09-15", CACHE)
    assert not r.passed and "ticket number" in r.reason


def test_activity_rejects_missing_section_and_template_comment():
    assert not check_activity(dump(activity_doc(summary=SUMMARY.replace("<b>Risks</b>", ""))), "2026-09-14", "2026-09-15", CACHE).passed
    assert not check_activity(dump(activity_doc(summary=SUMMARY + "<!-- x -->")), "2026-09-14", "2026-09-15", CACHE).passed


# ---- g2 -------------------------------------------------------------------

TODAY = date(2026, 9, 20)


def plan(entries):
    return {"week_start": "2026-09-14", "entries": entries, "issues": []}


def e(date_, day, kind, hours, comment="ao#1: One", tickets=("ao#1",)):
    return {"date": date_, "day": day, "entry": kind, "hours": hours, "comment": comment, "tickets": list(tickets)}


def test_plan_passes():
    p = plan([e("2026-09-14", "Mon", "Reg", 8), e("2026-09-14", "Mon", "Extra", 3),
              e("2026-09-15", "Tue", "Reg", 8, "Activity placeholder", ())])
    assert check_plan(p, {"Mon": 11, "Tue": 8}, activity_doc(), TODAY).passed


def test_plan_rejects_hour_mismatch_and_caps():
    assert not check_plan(plan([e("2026-09-14", "Mon", "Reg", 8)]), {"Mon": 9}, activity_doc(), TODAY).passed
    assert not check_plan(plan([e("2026-09-14", "Mon", "Reg", 9)]), {"Mon": 9}, activity_doc(), TODAY).passed
    assert not check_plan(plan([e("2026-09-14", "Mon", "Reg", 8), e("2026-09-14", "Mon", "Extra", 4)]), {"Mon": 12}, activity_doc(), TODAY).passed


def test_plan_rejects_extra_day_and_missing_day():
    assert not check_plan(plan([e("2026-09-14", "Mon", "Reg", 8)]), {"Mon": 8, "Tue": 8}, activity_doc(), TODAY).passed
    assert not check_plan(plan([e("2026-09-14", "Mon", "Reg", 8), e("2026-09-15", "Tue", "Reg", 8, "Activity placeholder", ())]), {"Mon": 8}, activity_doc(), TODAY).passed


def test_plan_rejects_ungrounded_ticket_and_long_comment():
    r = check_plan(plan([e("2026-09-14", "Mon", "Reg", 8, "ao#7: Nope", ("ao#7",))]), {"Mon": 8}, activity_doc(), TODAY)
    assert not r.passed and "ao#7" in r.reason
    assert not check_plan(plan([e("2026-09-14", "Mon", "Reg", 8, "x" * 256)]), {"Mon": 8}, activity_doc(), TODAY).passed


def test_plan_future_day_must_be_placeholder():
    p = plan([e("2026-09-16", "Wed", "Reg", 8, "ao#1: One")])
    assert not check_plan(p, {"Wed": 8}, activity_doc(), date(2026, 9, 13)).passed
    p = plan([e("2026-09-16", "Wed", "Reg", 8, "Activity placeholder", ())])
    assert check_plan(p, {"Wed": 8}, None, date(2026, 9, 13)).passed


# ---- g3 -------------------------------------------------------------------

def test_entry_passes_and_fails():
    p = plan([e("2026-09-14", "Mon", "Reg", 8), e("2026-09-14", "Mon", "Extra", 3)])
    ok = {"entries": [{"date": "2026-09-14", "entry": "Reg", "hours": 8, "status": "Entered"},
                      {"date": "2026-09-14", "entry": "Extra", "hours": 3, "status": "Entered"}],
          "totals": {"2026-09-14": 11}}
    assert check_entry(p, ok).passed
    bad_total = json.loads(json.dumps(ok)); bad_total["totals"]["2026-09-14"] = 8
    assert not check_entry(p, bad_total).passed
    bad_status = json.loads(json.dumps(ok)); bad_status["entries"][1]["status"] = "Error"
    assert not check_entry(p, bad_status).passed
    missing = json.loads(json.dumps(ok)); missing["entries"].pop()
    assert not check_entry(p, missing).passed


def test_entry_surfaces_step_error():
    r = check_entry(plan([e("2026-09-14", "Mon", "Reg", 8)]), {"entries": [], "totals": {}, "error": "LOGIN REQUIRED"})
    assert not r.passed and "LOGIN REQUIRED" in r.reason


# ---- g4 -------------------------------------------------------------------

def test_message_passes_modulo_whitespace_and_fails_on_change():
    ytext = dump(activity_doc())
    assert check_message(SUMMARY.replace("<br>", "<br>\n  "), ytext).passed
    assert not check_message(SUMMARY.replace("one thing", "two things"), ytext).passed


def test_message_rejects_ticket_numbers():
    doc = activity_doc(summary=SUMMARY.replace("<li>One</li>", "<li>DRA-563 One</li>"))
    assert not check_message(doc["summary"], dump(doc)).passed


# ---- adversarial parsing --------------------------------------------------

def test_parse_claims():
    assert parse_claims("[]") == []
    assert parse_claims('Here: ["a claim", "b"]') == ["a claim", "b"]
    assert parse_claims("no json here") is None
