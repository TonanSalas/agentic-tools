"""Repo discovery via the GitHub Events API."""

from . import dates, gh
from .config import ORG, GH_USERNAME


def discover_repos(start, end):
    """Use the Events API to find repos where the user had activity in the date range."""
    events = gh.gh_api(f"users/{GH_USERNAME}/events", {"per_page": "100"})
    repos = set()
    for event in events:
        created = dates.parse_date(event.get("created_at"))
        if not created:
            continue
        # Events API returns newest first; stop once we're before the range
        if created < start:
            break
        if not dates.date_in_range(created, start, end):
            continue
        repo_name = event.get("repo", {}).get("name", "")
        if repo_name.startswith(f"{ORG}/"):
            repos.add(repo_name)
    return sorted(repos)

