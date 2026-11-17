#!/usr/bin/env python3
"""Validate a tasks.json against the schema + the parallel-safety invariants.

Stdlib-only (checks are hand-coded; engine/schemas/tasks.schema.json stays the
documentation of record). The invariants make slice fan-out conflict-free:
every task in exactly one slice, intra-group deps only, disjoint writes across
groups, per-slice dependency order, acyclic.

Each slice group is built by its own agent (slice_pool.py), so a group must not grow past
MAX_GROUP_TASKS tasks when its tasks fall into independent parts: tasks that no depends_on chain
and no shared (or nested) write path connect. Such a group can always be split along those parts
without breaking another rule. A group whose tasks are all connected cannot be split and is never
capped; a slice's optional `keep_together` (the reason, one line) keeps a larger group whole.

Usage: python3 engine/validate_tasks.py <path-to-tasks.json>
Exit 0 = OK; exit 1 = FAIL (reason on stderr).
"""
import json
import sys
from pathlib import Path

MAX_GROUP_TASKS = 10


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _string_list(value, min_items=0):
    return (
        isinstance(value, list)
        and len(value) >= min_items
        and all(isinstance(v, str) and v for v in value)
    )


def check_schema(doc):
    """Hand-coded equivalent of tasks.schema.json. Returns an error string or None."""
    if not isinstance(doc, dict):
        return "document must be an object"
    required = {"schema_version", "stack", "feature_slug", "context_manifest", "slices", "tasks"}
    extra = set(doc) - required
    if extra:
        return f"unknown key(s): {', '.join(sorted(extra))}"
    missing = required - set(doc)
    if missing:
        return f"missing key(s): {', '.join(sorted(missing))}"
    if doc["schema_version"] != 1:
        return "schema_version must be 1"
    if not isinstance(doc["stack"], str) or not doc["stack"]:
        return "stack must be a non-empty repository name"
    if not isinstance(doc["feature_slug"], str) or not doc["feature_slug"]:
        return "feature_slug must be a non-empty string"
    cm = doc["context_manifest"]
    if not isinstance(cm, dict) or set(cm) != {"read_once", "reference"}:
        return "context_manifest must have exactly read_once + reference"
    if not _string_list(cm["read_once"]) or not _string_list(cm["reference"]):
        return "context_manifest lists must contain non-empty strings"
    if not isinstance(doc["slices"], list) or not doc["slices"]:
        return "slices must be a non-empty list"
    for i, sl in enumerate(doc["slices"]):
        if (not isinstance(sl, dict) or not {"group_id", "task_ids"} <= set(sl)
                or not set(sl) <= {"group_id", "task_ids", "keep_together"}):
            return f"slices[{i}] must have group_id + task_ids (and optionally keep_together)"
        if "keep_together" in sl and (not isinstance(sl["keep_together"], str)
                                      or not sl["keep_together"].strip()):
            return f"slices[{i}].keep_together must be a non-empty reason"
        if not isinstance(sl["group_id"], str) or not sl["group_id"]:
            return f"slices[{i}].group_id must be a non-empty string"
        if not _string_list(sl["task_ids"], min_items=1):
            return f"slices[{i}].task_ids must be a non-empty list of strings"
    if not isinstance(doc["tasks"], list) or not doc["tasks"]:
        return "tasks must be a non-empty list"
    task_required = {
        "id", "group_id", "title", "depends_on", "reads", "writes", "test",
        "standards", "needs_human_gate",
    }
    for i, t in enumerate(doc["tasks"]):
        if not isinstance(t, dict):
            return f"tasks[{i}] must be an object"
        extra = set(t) - task_required
        if extra:
            return f"tasks[{i}]: unknown key(s): {', '.join(sorted(extra))}"
        missing = task_required - set(t)
        if missing:
            return f"tasks[{i}]: missing key(s): {', '.join(sorted(missing))}"
        for key in ("id", "group_id", "title", "test"):
            if not isinstance(t[key], str) or not t[key]:
                return f"tasks[{i}].{key} must be a non-empty string"
        if not _string_list(t["depends_on"]) or not _string_list(t["reads"]):
            return f"tasks[{i}]: depends_on/reads must be lists of non-empty strings"
        if not _string_list(t["writes"], min_items=1):
            return f"tasks[{i}].writes must be a non-empty list of strings"
        if not isinstance(t["standards"], list) or not all(isinstance(s, str) for s in t["standards"]):
            return f"tasks[{i}].standards must be a list of strings"
        if not isinstance(t["needs_human_gate"], bool):
            return f"tasks[{i}].needs_human_gate must be a boolean"
    return None


def _nested(a, b):
    """The same path, or one inside the other (a directory and a file in it)."""
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def independent_parts(tasks):
    """Split one group's tasks into the parts nothing connects: a depends_on in either
    direction, or writes to the same (or a nested) path. Parts keep the tasks' order."""
    ids = [t["id"] for t in tasks]
    parent = {tid: tid for tid in ids}

    def find(tid):
        while parent[tid] != tid:
            parent[tid] = parent[parent[tid]]
            tid = parent[tid]
        return tid

    def join(a, b):
        parent[find(a)] = find(b)

    for t in tasks:
        for dep in t["depends_on"]:
            if dep in parent:
                join(t["id"], dep)
    for i, a in enumerate(tasks):
        for b in tasks[i + 1:]:
            if any(_nested(wa, wb) for wa in a["writes"] for wb in b["writes"]):
                join(a["id"], b["id"])
    parts = {}
    for tid in ids:
        parts.setdefault(find(tid), []).append(tid)
    return list(parts.values())


def check_group_sizes(doc, limit=MAX_GROUP_TASKS):
    """An error string for the first group over `limit` that could be split, or None."""
    tasks = {t["id"]: t for t in doc["tasks"]}
    for sl in doc["slices"]:
        if len(sl["task_ids"]) <= limit or sl.get("keep_together"):
            continue
        parts = independent_parts([tasks[tid] for tid in sl["task_ids"]])
        if len(parts) < 2:
            continue
        listed = "; ".join(f"[{', '.join(p)}]" for p in parts)
        return (
            f"slice {sl['group_id']} has {len(sl['task_ids'])} tasks (more than {limit}) in "
            f"{len(parts)} independent parts that no depends_on or shared write path connects: "
            f"{listed}. Each slice group is built by its own agent, so give each part its own "
            f"slice group (group_id) - combine small parts so each group stays at or under "
            f"{limit} tasks where possible, keeping writes disjoint across groups. If the parts "
            f"really must be built by one agent, add the missing depends_on, or set "
            f"\"keep_together\" on that slice to the reason (one line).")
    return None


def main():
    if len(sys.argv) != 2:
        fail("usage: validate_tasks.py <path-to-tasks.json>")
    path = Path(sys.argv[1])
    if not path.is_file():
        fail(f"not found: {path}")

    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"unparseable JSON: {exc}")
    error = check_schema(doc)
    if error:
        fail(f"schema: {error}")

    tasks = {t["id"]: t for t in doc["tasks"]}
    if len(tasks) != len(doc["tasks"]):
        fail("duplicate task id")

    # slice <-> task consistency
    slice_ids = set()
    for sl in doc["slices"]:
        if len(set(sl["task_ids"])) != len(sl["task_ids"]):
            fail(f"slice {sl['group_id']} lists a duplicate task_id")
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
                fail(
                    f"cross-group dependency: {t['id']} ({t['group_id']}) -> "
                    f"{dep} ({tasks[dep]['group_id']})"
                )

    # disjoint writes across groups
    owner = {}
    for t in doc["tasks"]:
        for w in t["writes"]:
            if w in owner and owner[w] != t["group_id"]:
                fail(f"write '{w}' shared by groups {owner[w]} and {t['group_id']}")
            owner[w] = t["group_id"]

    # per-slice: dependency order + acyclic
    for sl in doc["slices"]:
        seen = set()
        for tid in sl["task_ids"]:
            for dep in tasks[tid]["depends_on"]:
                if dep not in seen:
                    fail(f"slice {sl['group_id']}: {tid} listed before its dependency {dep}")
            seen.add(tid)

    # each group is one agent's work: an oversized group that could be split must be
    error = check_group_sizes(doc)
    if error:
        fail(error)

    print(f"OK: {path} ({len(tasks)} tasks, {len(doc['slices'])} slices)")


if __name__ == "__main__":
    main()
