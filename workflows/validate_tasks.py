#!/usr/bin/env python3
"""Validate a tasks.json against the schema + the parallel-safety invariants.

Usage: python3 workflows/validate_tasks.py <path-to-tasks.json>
Exit 0 = OK; exit 1 = FAIL (reason on stderr).
"""
import json
import sys
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).with_name("tasks.schema.json")


def fail(msg: str) -> "NoReturn":
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: validate_tasks.py <path-to-tasks.json>")
    path = Path(sys.argv[1])
    if not path.is_file():
        fail(f"not found: {path}")

    doc = json.loads(path.read_text())
    schema = json.loads(SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(doc, schema)
    except jsonschema.ValidationError as e:
        fail(f"schema: {e.message} (at {'/'.join(str(p) for p in e.absolute_path)})")

    tasks = {t["id"]: t for t in doc["tasks"]}
    if len(tasks) != len(doc["tasks"]):
        fail("duplicate task id")

    # slice <-> task consistency
    slice_ids = set()
    for sl in doc["slices"]:
        for tid in sl["task_ids"]:
            if tid not in tasks:
                fail(f"slice {sl['group_id']} references unknown task {tid}")
            if tasks[tid]["group_id"] != sl["group_id"]:
                fail(f"task {tid} group_id != slice {sl['group_id']}")
            slice_ids.add(tid)
    if slice_ids != set(tasks):
        fail(f"tasks not covered by exactly one slice: {set(tasks) ^ slice_ids}")

    # depends_on: exists + intra-group only
    for t in doc["tasks"]:
        for dep in t["depends_on"]:
            if dep not in tasks:
                fail(f"task {t['id']} depends on unknown {dep}")
            if tasks[dep]["group_id"] != t["group_id"]:
                fail(f"cross-group dependency: {t['id']} ({t['group_id']}) -> {dep} ({tasks[dep]['group_id']})")

    # disjoint writes across groups
    owner: dict[str, str] = {}
    for t in doc["tasks"]:
        for w in t["writes"]:
            if w in owner and owner[w] != t["group_id"]:
                fail(f"write '{w}' shared by groups {owner[w]} and {t['group_id']}")
            owner[w] = t["group_id"]

    # per-slice: dependency order + acyclic
    for sl in doc["slices"]:
        seen: set[str] = set()
        for tid in sl["task_ids"]:
            for dep in tasks[tid]["depends_on"]:
                if dep not in seen:
                    fail(f"slice {sl['group_id']}: {tid} listed before its dependency {dep}")
            seen.add(tid)

    print(f"OK: {path} ({len(tasks)} tasks, {len(doc['slices'])} slices)")


if __name__ == "__main__":
    main()
