#!/usr/bin/env python3
"""Decide how the PRD stage starts when no valid PRD exists yet: normalize the client's own PRD,
or clarify a short request through the interview.

  prd_source.py --requirement <dir> [--prd <dir>/prd.md]

A client document is any text document of at least MIN_WORDS words (Markdown, plain text, HTML)
or any office/PDF document in the requirement folder. A `prd.md` without Maestro's PRD header
metadata is the client's own file: it is copied once to `prd.original.md` so normalizing never
loses the original, and the copy is the source.

Prints one JSON line and always exits 0 (the workflow routes on `state`):
  {"state": "normalize" | "interview", "sources_csv", "source_count", "summary"}
"""
import argparse
import json
import os
import re
import shutil
import sys

MIN_WORDS = 250
TEXT_EXTS = {".md", ".markdown", ".txt", ".rst", ".html", ".htm"}
DOC_EXTS = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".pages"}
ORIGINAL = "prd.original.md"
# Maestro-written PRDs carry this header line (see validate_prd.FEATURE_SLUG_RE).
_MAESTRO_HEADER_RE = re.compile(r"^\*\*Feature slug:\*\*", re.IGNORECASE | re.MULTILINE)


def _words(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return len(re.findall(r"\b[\w'-]+\b", fh.read()))
    except OSError:
        return 0


def _is_maestro_prd(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return bool(_MAESTRO_HEADER_RE.search(fh.read()))
    except OSError:
        return False


def preserve_client_prd(prd_path):
    """Copy a client-authored prd.md to prd.original.md once. -> the copy's path, or None."""
    if not os.path.isfile(prd_path) or os.path.getsize(prd_path) == 0:
        return None
    original = os.path.join(os.path.dirname(prd_path), ORIGINAL)
    if _is_maestro_prd(prd_path):
        return original if os.path.isfile(original) else None
    if not os.path.exists(original):
        shutil.copyfile(prd_path, original)
    return original


def sources(requirement_dir, prd_path):
    preserve_client_prd(prd_path)
    found = []
    skip = os.path.realpath(prd_path)
    for dirpath, dirs, files in os.walk(requirement_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            if name.startswith(".") or os.path.realpath(path) == skip:
                continue
            ext = os.path.splitext(name)[1].lower()
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size and (ext in DOC_EXTS or (ext in TEXT_EXTS and _words(path) >= MIN_WORDS)):
                found.append(path)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requirement", required=True)
    parser.add_argument("--prd")
    args = parser.parse_args(argv)
    prd_path = args.prd or os.path.join(args.requirement, "prd.md")
    found = sources(args.requirement, prd_path)
    if found:
        names = ", ".join(os.path.basename(p) for p in found)
        summary = f"Normalized from the client's document: {names}"
    else:
        summary = "No client PRD found; clarified from the request"
    print(json.dumps({
        "state": "normalize" if found else "interview",
        "sources_csv": ",".join(found),
        "source_count": len(found),
        "summary": summary,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
