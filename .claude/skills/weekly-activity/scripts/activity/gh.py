"""The `gh` CLI shell-out layer: API calls, list searches, item metadata."""

import json
import subprocess
import sys

from .config import GH_USERNAME



def gh_api(endpoint, params=None, paginate=True):
    """Call gh api and return parsed JSON."""
    cmd = ["gh", "api", endpoint, "--method", "GET"]
    for k, v in (params or {}).items():
        cmd += ["-f", f"{k}={v}"]
    if paginate:
        cmd.append("--paginate")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Warning: gh api {endpoint} failed: {result.stderr}", file=sys.stderr)
        return []
    raw = result.stdout.strip()
    if not raw:
        return []
    # Fix paginated output: "][" -> ","
    raw = raw.replace("]\n[", ",").replace("][", ",")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"Warning: failed to parse JSON from {endpoint}", file=sys.stderr)
        return []


def gh_search(repo, resource, query_parts):
    """Use gh list commands for searching PRs/issues."""
    json_fields = "number,title,createdAt,mergedAt,body" if resource == "pr" else "number,title,createdAt"
    cmd = ["gh", resource, "list", "--repo", repo,
           f"--author={GH_USERNAME}", "--state=all",
           "--json", json_fields, "--limit", "100"]
    for part in query_parts:
        cmd.append(part)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Warning: gh {resource} list failed: {result.stderr}", file=sys.stderr)
        return []
    try:
        return json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return []


def fetch_item_meta(repo, number):
    """Fetch issue/PR metadata (title, state, state_reason, is_pr, merged) in one call.

    The /issues/{n} endpoint covers both issues and PRs; for PRs it includes a
    `pull_request` field with `merged_at`. Returns a dict with safe defaults
    if the call fails (e.g. ticket from another repo).
    """
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{number}"],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {
            "title": f"(unknown #{number})",
            "state": "unknown",
            "state_reason": None,
            "is_pr": False,
            "merged": None,
        }
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "title": f"(unknown #{number})",
            "state": "unknown",
            "state_reason": None,
            "is_pr": False,
            "merged": None,
        }
    pr_info = data.get("pull_request") or {}
    is_pr = bool(pr_info)
    merged = bool(pr_info.get("merged_at")) if is_pr else None
    return {
        "title": data.get("title", f"(unknown #{number})"),
        "state": (data.get("state") or "unknown").lower(),
        "state_reason": data.get("state_reason"),
        "is_pr": is_pr,
        "merged": merged,
    }


def fetch_item_title(repo, number):
    """Backwards-compatible: return just the title string."""
    return fetch_item_meta(repo, number)["title"]

