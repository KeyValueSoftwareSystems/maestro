#!/usr/bin/env python3
"""The run's todo list: a read-only, human-sized picture of where a run is.

Built from the workflow graph + the ledger, never by a model, so every surface shows the same
thing: `maestroctl todo` prints it, and `next` / `init` hand it to the lead agent to mirror
into the harness's own task list (Claude Code todos, a Codex plan, Cursor todos).

Items are STAGES — subworkflow and parallel nodes — in declaration order. Splitting large flows
into small stage children is what makes this list readable: `sdlc-main` shows design -> design
review -> delivery -> archive, and the running stage expands one level (design: intake -> PRD ->
map -> HLD -> LLDs -> contract). A stage is listed when it is on the workflow's normal path or
has been entered, so optional stages (the legacy import, a scoped architecture revision) appear
only once they actually run. The step the run is on is reported as a `now` line under the
innermost stage that contains it, marked `waiting` when it needs the human (a gate, an
interview, an exhausted-loop or failure question).

    build(run)  -> {"slug", "workflow", "status", "items": [...], "now": [...]}
    flat(todo)  -> [{"content", "status"}]   harness task-list shape (pending/in_progress/completed)
    render(todo) -> str                      the terminal checklist
"""

from __future__ import annotations

import hashlib
import json
import re

import resolver

STAGE_TYPES = ("subworkflow", "parallel")
HUMAN_TYPES = ("gate", "interview")
_TERMINAL = ("end", "abort")
_BRANCH_SEG = re.compile(r"^([a-z0-9_-]+)\[([a-z0-9_-]+)\]$")


def _label(node):
    return node.get("label") or node["id"].replace("_", " ").capitalize()


def _preferred_target(node, seen):
    """The normal next node: `next`, a gate's first option, a script's default route.

    Falls back to the first conditional route when the default would abort (a stage that only
    reports a decision routes on it and keeps `abort` as an unreachable default).
    """
    if node.get("next"):
        return node["next"]
    options = [o["to"] for o in node.get("options") or [] if o.get("to") != "abort"]
    routes = node.get("routes") or []
    default = [r["to"] for r in routes if r.get("when") in (None, "")]
    conditional = [r["to"] for r in routes if r.get("when") not in (None, "")]
    for target in options + [t for t in default if t != "abort"] + conditional:
        if target != "abort" and target not in seen:
            return target
    if not options and not routes:
        return "end"
    return None


def _normal_path(frame):
    seen, current = [], frame.start
    while current and current not in _TERMINAL and current not in seen and current in frame.nodes:
        seen.append(current)
        current = _preferred_target(frame.nodes[current], seen)
    return set(seen)


def _cursor_waiting(run, path):
    entry = run.state["steps"].get(path) or {}
    if entry.get("pending_ask") or entry.get("pending_gate_input"):
        return True
    try:
        _frame, node = run.node_at(path)
    except resolver.RunError:
        return False
    return resolver.ntype(node) in HUMAN_TYPES


def _now(run, path):
    try:
        _frame, node = run.node_at(path)
        label = _label(node)
    except resolver.RunError:
        label = path.rsplit("/", 1)[-1]
    branches = [m.group(2) for m in map(_BRANCH_SEG.match, path.split("/")[:-1]) if m]
    if branches:
        label = f"[{branches[-1]}] {label}"
    return {"label": label, "step": path, "waiting": _cursor_waiting(run, path)}


def _status(entry, now):
    status = (entry or {}).get("status") or "pending"
    if status == "pending" and (entry or {}).get("pending_ask"):
        return "waiting"
    if status == "running" and now and all(item["waiting"] for item in now):
        return "waiting"
    return status if status in ("done", "running", "failed", "skipped") else "pending"


def _owns(path, cursor):
    return cursor.startswith(path + "/") or cursor.startswith(path + "[")


def _stages(run, frame, cursors):
    """Stage items of `frame`; returns (items, cursors not claimed by any stage here)."""
    on_path = _normal_path(frame)
    items, claimed = [], set()
    for node in frame.workflow["nodes"]:
        if resolver.ntype(node) not in STAGE_TYPES:
            continue
        path = frame.path(node["id"])
        entry = run.state["steps"].get(path)
        if node["id"] not in on_path and entry is None:
            continue
        mine = [c for c in cursors if _owns(path, c) or c == path]
        claimed.update(mine)
        children, now = [], []
        if entry and entry.get("status") == "running" and resolver.ntype(node) == "subworkflow" \
                and path in run.state["frames"]:
            children, loose = _stages(run, run._sub_frame(frame, node), mine)
            now = [_now(run, c) for c in loose]
        else:
            now = [_now(run, c) for c in mine]
        items.append({
            "label": _label(node), "step": path, "status": _status(entry, now),
            "children": children, "now": now,
        })
    return items, [c for c in cursors if c not in claimed]


def build(run):
    state = run.state
    cursors = list(state["run"].get("cursors") or [])
    main = run.main_frame()
    items, loose = _stages(run, main, cursors)
    return {
        "slug": state.get("slug") or run.slug,
        "workflow": main.workflow.get("name") or state["workflow"]["file"],
        "status": state["run"]["status"],
        "items": items,
        "now": [_now(run, c) for c in loose],
    }


def digest(todo):
    """Stable hash of what the human would see — `next` re-sends the list only when it moves."""
    view = {k: todo[k] for k in ("status", "items", "now")}
    return hashlib.sha256(json.dumps(view, sort_keys=True).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- presentation

_HARNESS = {"done": "completed", "skipped": "completed", "running": "in_progress",
            "waiting": "in_progress", "failed": "in_progress", "pending": "pending"}
_MARK = {"done": "[x]", "skipped": "[-]", "running": "[>]", "waiting": "[?]",
         "failed": "[!]", "pending": "[ ]"}


def _now_text(now):
    waiting = [n["label"] for n in now if n["waiting"]]
    working = [n["label"] for n in now if not n["waiting"]]
    parts = []
    if waiting:
        parts.append("waiting on you: " + ", ".join(waiting))
    if working:
        parts.append("now: " + ", ".join(working))
    return "; ".join(parts)


def flat(todo):
    """One harness task per stage; a running stage's children follow as `Parent › Child`."""
    out = []

    def walk(items, parent):
        for item in items:
            text = f"{parent} › {item['label']}" if parent else item["label"]
            detail = _now_text(item["now"])
            if item["status"] == "failed":
                detail = "failed" + (f"; {detail}" if detail else "")
            out.append({"content": f"{text} — {detail}" if detail else text,
                        "status": _HARNESS[item["status"]]})
            walk(item["children"], text)

    walk(todo["items"], "")
    if todo["now"]:
        out.append({"content": _now_text(todo["now"]), "status": "in_progress"})
    return out


def render(todo):
    lines = [f"{todo['slug']} · {todo['workflow']} · {todo['status']}"]

    def walk(items, depth):
        pad = "    " * depth
        for item in items:
            lines.append(f"{pad}{_MARK[item['status']]} {item['label']}")
            detail = _now_text(item["now"])
            if detail:
                lines.append(f"{pad}      ↳ {detail}")
            walk(item["children"], depth + 1)

    walk(todo["items"], 0)
    if todo["now"]:
        lines.append(f"      ↳ {_now_text(todo['now'])}")
    return "\n".join(lines)
