#!/usr/bin/env python3
"""Convert a message (markdown or HTML) into the simple HTML Teams renders well,
and optionally place it on the macOS clipboard with the text/html MIME type.

    python3 to_teams_html.py --in msg.md --out /tmp/teams-msg.html [--clipboard]

Rules (tested in tests/test_to_teams_html.py):
- Input that starts with '<' is treated as HTML and passed through; an
  enclosing <html>...</html> wrapper is removed.
- Markdown: '# H' / '## H' -> <b>H</b><br>; '**x**' -> <b>x</b>; runs of
  '* item' / '- item' -> one <ul>; blank line -> <br>; other lines -> <p>.
- The --clipboard step uses Swift/NSPasteboard: it is the only approach found
  that sets the HTML pasteboard type correctly (osascript and Python AppKit
  do not).
"""
from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_WRAPPER_RE = re.compile(r"^\s*<html>\s*|\s*</html>\s*$", re.I)


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    return _BOLD_RE.sub(r"<b>\1</b>", escaped)


def to_html(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("<"):
        return _WRAPPER_RE.sub("", stripped).strip()

    out: list[str] = []
    in_list = False
    for raw in stripped.splitlines():
        line = raw.rstrip()
        is_bullet = line.lstrip().startswith(("* ", "- "))
        if in_list and not is_bullet:
            out.append("</ul>")
            in_list = False
        if is_bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line.lstrip()[2:].strip())}</li>")
        elif not line.strip():
            out.append("<br>")
        elif line.startswith("#"):
            out.append(f"<b>{_inline(line.lstrip('#').strip())}</b><br>")
        else:
            out.append(f"<p>{_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


SWIFT_SNIPPET = """
import AppKit
let html = try! String(contentsOfFile: "{path}", encoding: .utf8)
let pb = NSPasteboard.general
pb.clearContents()
pb.setString(html, forType: .html)
"""


def set_clipboard_html(html_text: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_text)
        path = f.name
    subprocess.run(["swift", "-e", SWIFT_SNIPPET.format(path=path)], check=True)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--in", dest="inp", required=True, help="message file (markdown or HTML)")
    p.add_argument("--out", help="write the HTML here as well as stdout")
    p.add_argument("--clipboard", action="store_true", help="also put it on the macOS clipboard as text/html")
    a = p.parse_args(argv)
    result = to_html(Path(a.inp).read_text(encoding="utf-8"))
    if a.out:
        Path(a.out).write_text(result, encoding="utf-8")
    if a.clipboard:
        set_clipboard_html(result)
        print("clipboard: set text/html", file=sys.stderr)
    print(result)


if __name__ == "__main__":
    main()
