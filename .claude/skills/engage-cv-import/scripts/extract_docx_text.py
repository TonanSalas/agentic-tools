#!/usr/bin/env python3
"""
Extract plain text from a .docx CV so it can be read the same way a PDF's
rendered text is (Claude's Read tool reads PDFs directly, but not .docx).

A .docx is a zip archive containing word/document.xml, which holds the
document body as WordprocessingML. This walks that XML directly with the
standard library instead of adding a python-docx dependency, matching this
repo's zero-external-dependency convention for scripts.
"""

import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _run_aware_text(element):
    """Extract text from all descendants of `element` in document order, run-aware:
    `w:t` contributes its text, `w:tab` contributes a space, and `w:br` contributes a
    newline. Without this, a tab or line break between two `w:t` runs (siblings inside a
    `w:r`) contributes nothing, silently concatenating words that were visually separated
    (e.g. "Backend Engineer<TAB>Jan 2022" -> "Backend EngineerJan 2022")."""
    parts = []
    for node in element.iter():
        tag = node.tag
        if tag == f"{WORD_NS}t":
            parts.append(node.text or "")
        elif tag == f"{WORD_NS}tab":
            parts.append(" ")
        elif tag == f"{WORD_NS}br":
            parts.append("\n")
    return "".join(parts)


def extract_text(docx_path):
    """Return the docx's visible text: one line per paragraph, table rows as 'cell | cell'."""
    with zipfile.ZipFile(docx_path) as archive:
        xml_bytes = archive.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    body = root.find(f"{WORD_NS}body")

    lines = []
    for element in body:
        tag = element.tag
        if tag == f"{WORD_NS}p":
            text = _run_aware_text(element).strip()
            if text:
                lines.append(text)
        elif tag == f"{WORD_NS}tbl":
            for row in element.iter(f"{WORD_NS}tr"):
                cells = []
                for cell in row.iter(f"{WORD_NS}tc"):
                    cell_text = _run_aware_text(cell).strip()
                    if cell_text:
                        cells.append(cell_text)
                if cells:
                    lines.append(" | ".join(cells))

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Extract plain text from a .docx CV")
    parser.add_argument("docx_path", help="Path to the .docx file")
    parser.add_argument("--out", help="Write extracted text to this path instead of stdout")
    args = parser.parse_args()

    path = Path(args.docx_path)
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        text = extract_text(path)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        print(f"Error: could not read '{path}' as a .docx file ({e})", file=sys.stderr)
        sys.exit(1)

    if args.out:
        Path(args.out).write_text(text)
        print(f"Wrote {len(text)} chars to {args.out}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
