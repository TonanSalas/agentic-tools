"""Cross-repo assembly: fan out over discovered repos, merge into one payload."""

import sys
from collections import defaultdict
from datetime import datetime, timedelta

from .config import LOCAL_TZ, GH_USERNAME
from . import collect, discovery, parsing


def gather_all(start, end):
    """Run the full discovery + per-repo gather and return a JSON-serializable dict."""
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    api_since = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    api_until = (end_dt + timedelta(days=2)).strftime("%Y-%m-%d")

    repos = discovery.discover_repos(api_since, api_until)
    if not repos:
        return {
            "generated_at": datetime.now(LOCAL_TZ).isoformat(),
            "start": start,
            "end": end,
            "repos": [],
            "days": {},
            "tickets": [],
        }

    print(f"Repos with activity: {', '.join(r.split('/')[-1] for r in repos)}", file=sys.stderr)

    merged_activity = defaultdict(lambda: defaultdict(lambda: {"title": "", "sources": set()}))
    merged_meta = {}  # (repo, num) -> meta dict

    for repo in repos:
        print(f"Gathering activity from {repo}...", file=sys.stderr)
        activity, _pr_nums, _pr_comment_nums, _review_pr_nums, _prs, meta_by_key = \
            collect.gather_repo_activity(repo, start, end, api_since, api_until)

        for day, day_data in activity.items():
            for k, info in day_data.items():
                entry = merged_activity[day][k]
                if info["title"]:
                    entry["title"] = info["title"]
                entry["sources"].update(info["sources"])

        merged_meta.update(meta_by_key)

    # References GitHub answered "no such item" for were never tickets -- a
    # #ref scraped out of a PR body can be a quote id, an invoice number, any
    # "#" followed by digits. Drop those. Keep the ones we merely failed to
    # reach: unreachable is not the same as nonexistent, and dropping a real
    # ticket because of a rate limit would lose work silently.
    missing = {k for k, m in merged_meta.items() if m.get("resolution") == "missing"}
    if missing:
        print(f"Dropped {len(missing)} unresolvable reference(s): "
              + ", ".join(f"{r.split('/')[-1]}#{n}" for r, n in sorted(missing)),
              file=sys.stderr)

    # Build per-ticket dedup view: (repo, num) -> {meta, days, sources}
    tickets_index = {}
    for day, day_data in merged_activity.items():
        for (repo, num), info in day_data.items():
            if (repo, num) in missing:
                continue
            t = tickets_index.setdefault((repo, num), {
                "days": set(),
                "sources": set(),
            })
            t["days"].add(day)
            t["sources"].update(info["sources"])

    tickets_list = []
    for (repo, num), t in sorted(tickets_index.items()):
        meta = merged_meta.get((repo, num), {})
        tickets_list.append({
            "repo": repo.split("/")[-1],
            "number": num,
            "title": meta.get("title") or f"(unknown #{num})",
            "state": meta.get("state", "unknown"),
            "state_reason": meta.get("state_reason"),
            "is_pr": meta.get("is_pr", False),
            "merged": meta.get("merged"),
            "days": sorted(t["days"]),
            "sources": sorted(t["sources"]),
        })

    # Per-day view (for workday-timelogger): day -> [ticket dicts]
    days_view = {}
    ticket_lookup = {(t["repo"], t["number"]): t for t in tickets_list}
    for day, day_data in merged_activity.items():
        items = []
        for (repo, num), info in sorted(day_data.items()):
            if (repo, num) in missing:
                continue
            short = repo.split("/")[-1]
            base = ticket_lookup.get((short, num), {})
            items.append({
                "repo": short,
                "number": num,
                "title": info["title"] or base.get("title") or f"(unknown #{num})",
                "state": base.get("state", "unknown"),
                "state_reason": base.get("state_reason"),
                "is_pr": base.get("is_pr", False),
                "merged": base.get("merged"),
                "sources": sorted(info["sources"]),
            })
        days_view[day] = items

    return {
        "generated_at": datetime.now(LOCAL_TZ).isoformat(),
        "start": start,
        "end": end,
        "repos": [r.split("/")[-1] for r in repos],
        "days": days_view,
        "tickets": tickets_list,
    }

