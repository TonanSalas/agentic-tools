"""Text parsing: commit-title cleanup and ticket-reference extraction."""

import re


def strip_conventional_prefix(title):
    """Remove conventional commit prefixes like feat:, fix(scope):, etc."""
    return re.sub(r"^(feat|fix|chore|docs|refactor|test|ci|build|perf|style|revert)(\([^)]*\))?:\s*", "", title, flags=re.IGNORECASE)


def extract_ticket_refs(text):
    """Extract ticket numbers from text (#NNN patterns).

    The digits must not be followed by a word character, or CSS hex colours
    become tickets: bare `#(\\d+)` reads `#662CBE` as #662, which is how a
    colour in a PR body once minted a phantom ticket. `PR#42` still resolves --
    only the right-hand boundary is enforced, since a ref glued to a preceding
    word is still a ref.
    """
    if not text:
        return []
    return [int(m) for m in re.findall(r"#(\d+)(?!\w)", text)]
