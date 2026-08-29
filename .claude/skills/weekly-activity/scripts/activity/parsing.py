"""Text parsing: commit-title cleanup and ticket-reference extraction."""

import re


def strip_conventional_prefix(title):
    """Remove conventional commit prefixes like feat:, fix(scope):, etc."""
    return re.sub(r"^(feat|fix|chore|docs|refactor|test|ci|build|perf|style|revert)(\([^)]*\))?:\s*", "", title, flags=re.IGNORECASE)


def extract_ticket_refs(text):
    """Extract ticket numbers from text (#NNN patterns)."""
    if not text:
        return []
    return [int(m) for m in re.findall(r"#(\d+)", text)]
