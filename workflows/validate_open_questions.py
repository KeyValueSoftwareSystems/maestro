#!/usr/bin/env python3
"""Validate an open-questions.json against the schema + status/resolution invariants.

Usage: python3 workflows/validate_open_questions.py <path-to-open-questions.json>
Exit 0 = OK; exit 1 = FAIL (reason on stderr).
"""
import json
import sys
from pathlib import Path
from typing import NoReturn

import jsonschema

SCHEMA_PATH = Path(__file__).with_name("open-questions.schema.json")

# Which resolution.kind values each status permits. `open` requires resolution null.
ALLOWED_KINDS: dict[str, set[str]] = {
    "resolved": {"picked", "other", "you-decide"},
    "folded": {"picked", "other", "you-decide"},
    "deferred": {"skip"},
}


def fail(msg: str) -> NoReturn:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: validate_open_questions.py <path-to-open-questions.json>")
    path = Path(sys.argv[1])
    if not path.is_file():
        fail(f"not found: {path}")

    doc = json.loads(path.read_text())
    schema = json.loads(SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(doc, schema)
    except jsonschema.ValidationError as e:
        fail(f"schema: {e.message} (at {'/'.join(str(p) for p in e.absolute_path)})")

    ids = [q["id"] for q in doc["questions"]]
    if len(set(ids)) != len(ids):
        fail("duplicate question id")

    # status <-> resolution consistency
    for q in doc["questions"]:
        status, res = q["status"], q["resolution"]
        if status == "open":
            if res is not None:
                fail(f"question {q['id']}: status 'open' must have null resolution")
            continue
        if status == "deferred" and res is None:
            continue  # deferred may be recorded with either null or a skip resolution
        if res is None:
            fail(f"question {q['id']}: status '{status}' requires a resolution")
        if res["kind"] not in ALLOWED_KINDS[status]:
            fail(
                f"question {q['id']}: status '{status}' does not allow "
                f"resolution kind '{res['kind']}'"
            )

    n_open = sum(1 for q in doc["questions"] if q["status"] == "open")
    print(f"OK: {path} ({len(ids)} questions, {n_open} open)")


if __name__ == "__main__":
    main()
