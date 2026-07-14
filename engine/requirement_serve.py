#!/usr/bin/env python3
"""Serve the "is a requirement present?" routing state (workflows/design.yaml).

Reads a requirement folder and prints a JSON object to stdout so the design
workflow's script node can route on the `state` field (the "script stdout JSON
becomes routable outputs" pattern, same as oq_serve.py):

  {"state": "have"}  -> at least one non-empty file exists -> author the HLD
  {"state": "need"}  -> the folder is missing or empty      -> intake / brainstorm

Routing is on `state`, never the exit code: this always exits 0 so a missing
folder is a normal "need", not a script failure.

Usage: python3 engine/requirement_serve.py <path-to-requirement-dir>
"""
import json
import os
import sys
from pathlib import Path
from typing import NoReturn


def fail(msg: str) -> NoReturn:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def has_requirement(directory: Path) -> bool:
    """True if the folder holds at least one non-empty regular file (recursively)."""
    if not directory.is_dir():
        return False
    for dirpath, _dirs, files in os.walk(directory):
        for name in files:
            try:
                if os.path.getsize(os.path.join(dirpath, name)) > 0:
                    return True
            except OSError:
                continue
    return False


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: requirement_serve.py <path-to-requirement-dir>")
    directory = Path(sys.argv[1])
    state = "have" if has_requirement(directory) else "need"
    print(json.dumps({"state": state}))


if __name__ == "__main__":
    main()
