"""Markdown rendering of an already-gathered payload."""

from collections import defaultdict
from datetime import datetime, timedelta

from .config import DAY_NAMES, GH_USERNAME


def render_markdown(data):
    """Render the dict from gather_all() as the original markdown table."""
    start = data["start"]
    end = data["end"]
    repos = data["repos"]

    if not repos:
        return f"No activity found for {GH_USERNAME} between {start} and {end}."

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    multi_repo = len(repos) > 1

    def format_ticket(repo, num, title):
        if multi_repo:
            return f"{repo}#{num}: {title}"
        return f"#{num}: {title}"

    lines = []
    lines.append(f"## Weekly Activity: {start_dt.strftime('%A')} {start} - {end_dt.strftime('%A')} {end}, {start_dt.year}")
    lines.append("")
    lines.append("| Day       | Tickets & PRs | Source |")
    lines.append("|-----------|---------------|--------|")

    current = start_dt
    while current <= end_dt:
        day_str = current.strftime("%Y-%m-%d")
        day_abbr = DAY_NAMES[current.weekday()]
        day_label = f"{day_abbr} {current.strftime('%m/%d')}"

        items = data["days"].get(day_str, [])
        if items:
            ticket_parts = [format_ticket(it["repo"], it["number"], it["title"]) for it in items]
            source_parts = [it["sources"][0] if it["sources"] else "" for it in items]
            lines.append(f"| {day_label} | {', '.join(ticket_parts)} | {', '.join(source_parts)} |")
        else:
            lines.append(f"| {day_label} | No activity | |")
        current += timedelta(days=1)

    # Summary
    pr_tickets = [t for t in data["tickets"] if t["is_pr"]]
    merged_count = sum(1 for t in pr_tickets if t["merged"])
    open_count = len(pr_tickets) - merged_count

    lines.append("")
    lines.append("### Summary")
    lines.append(f"- Repos: {', '.join(repos)}")
    lines.append(f"- Total Tickets Touched: {len(data['tickets'])}")
    lines.append(f"- Total PRs: {len(pr_tickets)} ({merged_count} merged, {open_count} open)")

    return "\n".join(lines)

