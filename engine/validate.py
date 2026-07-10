"""Workflow validation: schema checks + graph lint.

Mirrors engine/schemas/workflow.schema.json (kept in sync by review + the UI sync test)
but is hand-coded so the engine stays stdlib-only. Rules carry stable ids — the builder
UI implements a declared subset client-side and a parity test compares the id lists.

Levels: 'error' blocks a run; 'warning' does not.
"""

from __future__ import annotations

import os
import re

try:
    import condctl
    import wf
except ImportError:
    from . import condctl, wf

# Rule ids implemented here. The UI embeds the subset it mirrors; testdata's parity test
# asserts every UI rule id exists in this list.
RULE_IDS = [
    "bad-yaml", "bad-version", "bad-name", "missing-key", "unknown-key", "bad-type",
    "dup-id", "bad-id", "no-start", "missing-route-target", "no-default-route",
    "bad-condition", "gate-no-options", "gate-dup-options", "route-and-next",
    "no-routing", "unreachable-node", "bad-placeholder", "undeclared-input",
    "parallel-too-few-branches", "branch-bad-start", "branch-bad-type",
    "subworkflow-missing-file", "subworkflow-too-deep", "subworkflow-cycle",
    "cycle-no-brake", "bad-max-visits", "artifact-not-string", "empty-instruction",
]

MAX_DEPTH = 4
RESERVED = ("end", "abort")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")

_TOP_KEYS = {"version", "name", "description", "inputs", "defaults", "start", "nodes", "outputs", "ui"}
_ROUTING_KEYS = {"next", "routes", "on_fail", "max_visits", "on_exhausted"}
_NODE_KEYS = {
    "agent": {"id", "type", "label", "instruction", "skill", "agent", "model", "inputs",
              "outputs", "artifact", "retries", "isolate", "ui"} | _ROUTING_KEYS,
    "gate": {"id", "type", "label", "prompt", "options", "max_visits", "on_exhausted", "ui"},
    "script": {"id", "type", "label", "run", "timeout", "ui"} | _ROUTING_KEYS,
    "parallel": {"id", "type", "label", "join", "on_branch_fail", "branches", "isolate", "ui"} | _ROUTING_KEYS,
    "subworkflow": {"id", "type", "label", "workflow", "inputs", "ui"} | _ROUTING_KEYS,
}
_BRANCH_NODE_TYPES = {"agent", "gate", "script", "subworkflow"}


class Issue:
    def __init__(self, level, code, msg, where=None):
        self.level, self.code, self.msg, self.where = level, code, msg, where

    def __str__(self):
        loc = f" [{self.where}]" if self.where else ""
        return f"{self.level}: {self.code}: {self.msg}{loc}"


def validate_file(path, root=".", _depth=0, _stack=None):
    """Validate a workflow file (and its subworkflows, recursively). -> [Issue]"""
    issues = []
    _stack = list(_stack or [])
    rel = os.path.relpath(path, root) if os.path.isabs(path) else path
    norm = os.path.normpath(rel)
    if norm in _stack:
        return [Issue("error", "subworkflow-cycle", f"subworkflow cycle: {' -> '.join(_stack + [norm])}")]
    if _depth > MAX_DEPTH:
        return [Issue("error", "subworkflow-too-deep", f"nesting deeper than {MAX_DEPTH}: {norm}")]
    full = os.path.join(root, norm)
    try:
        doc = wf.load_file(full)
    except (wf.WfError, OSError) as exc:
        return [Issue("error", "bad-yaml", f"{norm}: {exc}")]
    issues.extend(validate_doc(doc, where=norm))

    # recurse into subworkflow files (top-level nodes and inside parallel branches)
    def sub_nodes(node_list):
        for node in node_list or []:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "subworkflow":
                yield node
            for branch in node.get("branches") or []:
                if isinstance(branch, dict):
                    yield from sub_nodes(branch.get("steps"))

    for node in sub_nodes((doc.get("nodes") or []) if isinstance(doc, dict) else []):
        if not isinstance(node.get("workflow"), str):
            continue
        child = node["workflow"]
        child_full = os.path.join(root, child)
        if not os.path.exists(child_full):
            issues.append(Issue("error", "subworkflow-missing-file",
                                f"node {node.get('id')}: file not found: {child}", norm))
        else:
            issues.extend(validate_file(child, root, _depth + 1, _stack + [norm]))
    return issues


def validate_doc(doc, where=""):
    issues = []
    err = lambda code, msg, w=None: issues.append(Issue("error", code, msg, w or where))
    warn = lambda code, msg, w=None: issues.append(Issue("warning", code, msg, w or where))

    if not isinstance(doc, dict):
        err("bad-yaml", "workflow must be a mapping")
        return issues
    for key in doc:
        if key not in _TOP_KEYS:
            err("unknown-key", f"unknown top-level key {key!r}")
    for key in ("version", "name", "start", "nodes"):
        if key not in doc:
            err("missing-key", f"missing required top-level key {key!r}")
    if "version" in doc and doc["version"] != 1:
        err("bad-version", f"unsupported version {doc['version']!r} (expected 1)")
    if "name" in doc and (not isinstance(doc["name"], str) or not _NAME_RE.match(doc["name"])):
        err("bad-name", f"name must be kebab-case: {doc.get('name')!r}")
    if "max_visits" in (doc.get("defaults") or {}):
        mv = doc["defaults"]["max_visits"]
        if not isinstance(mv, int) or mv < 1:
            err("bad-max-visits", f"defaults.max_visits must be a positive integer, got {mv!r}")

    declared_inputs = set((doc.get("inputs") or {}).keys()) | {"slug"}
    nodes = doc.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        err("bad-type", "nodes must be a non-empty list")
        return issues

    ids = {}
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            err("bad-type", f"nodes[{i}] must be a mapping")
            continue
        nid = node.get("id")
        if not isinstance(nid, str) or not _ID_RE.match(nid) or nid in RESERVED:
            err("bad-id", f"nodes[{i}]: bad or missing id {nid!r}")
            continue
        if nid in ids:
            err("dup-id", f"duplicate node id {nid!r}")
        ids[nid] = node

    start = doc.get("start")
    if start is not None and start not in ids:
        err("no-start", f"start {start!r} is not a node id")

    for node in nodes:
        if isinstance(node, dict) and node.get("id") in ids:
            issues.extend(_validate_node(node, ids, declared_inputs, where))

    if start in ids:
        reachable = _reachable(ids, start)
        for nid in ids:
            if nid not in reachable:
                warn("unreachable-node", f"node {nid!r} is unreachable from start")
        for cyc in _find_cycles(ids):
            kinds = {ids[n].get("type") for n in cyc}
            if "gate" not in kinds and "script" not in kinds:
                warn("cycle-no-brake",
                     f"cycle {' -> '.join(cyc)} contains no gate and no script — "
                     f"agent-only loops burn tokens with nothing deterministic to stop them")
    return issues


def _validate_node(node, ids, declared_inputs, where):
    issues = []
    nid = node["id"]
    w = f"{where}#{nid}" if where else nid
    err = lambda code, msg: issues.append(Issue("error", code, msg, w))
    warn = lambda code, msg: issues.append(Issue("warning", code, msg, w))

    ntype = node.get("type")
    if ntype not in _NODE_KEYS:
        err("bad-type", f"unknown node type {ntype!r}")
        return issues
    for key in node:
        if key not in _NODE_KEYS[ntype]:
            err("unknown-key", f"{ntype} node has unknown key {key!r}")

    # type-specific requireds
    if ntype == "agent":
        instruction = node.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            err("empty-instruction", "agent node needs a non-empty instruction")
        art = node.get("artifact")
        if art is not None and not (
            isinstance(art, str) or (isinstance(art, list) and all(isinstance(a, str) for a in art))
        ):
            err("artifact-not-string", "artifact must be a string or list of strings")
    elif ntype == "gate":
        options = node.get("options")
        if not isinstance(options, list) or not options:
            err("gate-no-options", "gate needs at least one option")
            options = []
        seen = set()
        for opt in options:
            if not isinstance(opt, dict) or not all(k in opt for k in ("id", "label", "to")):
                err("missing-key", f"gate option must have id/label/to: {opt!r}")
                continue
            if opt["id"] in seen:
                err("gate-dup-options", f"duplicate option id {opt['id']!r}")
            seen.add(opt["id"])
            if opt["to"] not in ids and opt["to"] not in RESERVED:
                err("missing-route-target", f"option {opt['id']!r} targets unknown node {opt['to']!r}")
            for k in opt:
                if k not in ("id", "label", "to", "input"):
                    err("unknown-key", f"gate option has unknown key {k!r}")
    elif ntype == "script":
        run = node.get("run")
        if not isinstance(run, list) or not run or not all(isinstance(a, str) for a in run):
            err("bad-type", "script run must be a non-empty list of strings (argv)")
    elif ntype == "parallel":
        branches = node.get("branches")
        if not isinstance(branches, list) or len(branches) < 2:
            err("parallel-too-few-branches", "parallel needs at least two branches")
            branches = []
        bids = set()
        for branch in branches:
            if not isinstance(branch, dict) or not all(k in branch for k in ("id", "start", "steps")):
                err("missing-key", f"branch must have id/start/steps: {branch!r}")
                continue
            if branch["id"] in bids:
                err("dup-id", f"duplicate branch id {branch['id']!r}")
            bids.add(branch["id"])
            steps = branch.get("steps") or []
            bids_map = {}
            for step in steps:
                if not isinstance(step, dict):
                    err("bad-type", f"branch {branch['id']}: steps must be mappings")
                    continue
                if step.get("type") not in _BRANCH_NODE_TYPES:
                    err("branch-bad-type",
                        f"branch {branch['id']}: node {step.get('id')!r} has type "
                        f"{step.get('type')!r} (only agent/gate/script/subworkflow inside branches)")
                    continue
                sid = step.get("id")
                if not isinstance(sid, str) or not _ID_RE.match(sid):
                    err("bad-id", f"branch {branch['id']}: bad step id {sid!r}")
                    continue
                if sid in bids_map:
                    err("dup-id", f"branch {branch['id']}: duplicate step id {sid!r}")
                bids_map[sid] = step
            if branch.get("start") not in bids_map:
                err("branch-bad-start", f"branch {branch['id']}: start {branch.get('start')!r} not in steps")
            for step in steps:
                if isinstance(step, dict) and step.get("id") in bids_map and step.get("type") in _BRANCH_NODE_TYPES:
                    issues.extend(_validate_node(step, bids_map, declared_inputs, f"{w}[{branch['id']}]"))
    elif ntype == "subworkflow":
        if not isinstance(node.get("workflow"), str):
            err("missing-key", "subworkflow needs a workflow file path")

    # routing
    if ntype != "gate":
        has_next, has_routes = "next" in node, "routes" in node
        if has_next and has_routes:
            err("route-and-next", "use either next or routes, not both")
        elif not has_next and not has_routes:
            err("no-routing", f"{ntype} node needs next or routes")
        if has_next and node["next"] not in ids and node["next"] not in RESERVED:
            err("missing-route-target", f"next targets unknown node {node['next']!r}")
        if has_routes:
            routes = node["routes"]
            if not isinstance(routes, list) or not routes:
                err("bad-type", "routes must be a non-empty list")
                routes = []
            default_seen = False
            for i, route in enumerate(routes):
                if not isinstance(route, dict) or "to" not in route:
                    err("missing-key", f"routes[{i}] must have a to")
                    continue
                if route["to"] not in ids and route["to"] not in RESERVED:
                    err("missing-route-target", f"routes[{i}] targets unknown node {route['to']!r}")
                cond = route.get("when")
                if cond in (None, ""):
                    default_seen = True
                    if i != len(routes) - 1:
                        err("no-default-route", "the default route (no when) must be last")
                else:
                    try:
                        condctl.parse(cond)
                    except condctl.CondError as exc:
                        err("bad-condition", str(exc))
            if not default_seen:
                err("no-default-route", "routes need a final default entry with no when")
    for key in ("on_fail", "on_exhausted"):
        value = node.get(key)
        if value and value not in ("abort", "ask") and value not in ids:
            issues.append(Issue("error", "missing-route-target",
                                f"{key} targets unknown node {value!r}", w))
    mv = node.get("max_visits")
    if mv is not None and not (isinstance(mv, int) and mv >= 1) and not (
        isinstance(mv, str) and _PLACEHOLDER_RE.search(mv)
    ):
        issues.append(Issue("error", "bad-max-visits", f"max_visits must be a positive integer", w))

    # static placeholder checks over every string in the node
    for text in _strings(node):
        for m in _PLACEHOLDER_RE.finditer(text):
            ref = m.group(1).strip()
            parts = ref.split(".")
            if parts[0] == "inputs" and len(parts) == 2:
                if parts[1] not in declared_inputs:
                    issues.append(Issue("error", "undeclared-input",
                                        f"${{{ref}}} references undeclared input", w))
            elif parts[0] == "steps" and len(parts) >= 3:
                if parts[1] not in ids:
                    # may be an outer-frame id when inside a branch — only warn
                    issues.append(Issue("warning", "bad-placeholder",
                                        f"${{{ref}}}: no node {parts[1]!r} in this scope", w))
            elif parts[0] == "config":
                pass
            else:
                issues.append(Issue("error", "bad-placeholder", f"malformed placeholder ${{{ref}}}", w))
    return issues


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k == "ui":
                continue
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _edges(node):
    targets = []
    if isinstance(node.get("next"), str):
        targets.append(node["next"])
    for route in node.get("routes") or []:
        if isinstance(route, dict) and isinstance(route.get("to"), str):
            targets.append(route["to"])
    for option in node.get("options") or []:
        if isinstance(option, dict) and isinstance(option.get("to"), str):
            targets.append(option["to"])
    for key in ("on_fail", "on_exhausted"):
        value = node.get(key)
        if isinstance(value, str) and value not in ("abort", "ask"):
            targets.append(value)
    return [t for t in targets if t not in RESERVED]


def _reachable(ids, start):
    seen, stack = set(), [start]
    while stack:
        nid = stack.pop()
        if nid in seen or nid not in ids:
            continue
        seen.add(nid)
        stack.extend(_edges(ids[nid]))
    return seen


def _find_cycles(ids):
    """Return one representative node list per strongly-connected cycle (Tarjan-lite)."""
    cycles = []
    index, low, on_stack, stack = {}, {}, set(), []
    counter = [0]

    def strongconnect(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for t in _edges(ids[v]):
            if t not in ids:
                continue
            if t not in index:
                strongconnect(t)
                low[v] = min(low[v], low[t])
            elif t in on_stack:
                low[v] = min(low[v], index[t])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or v in _edges(ids[v]):
                cycles.append(list(reversed(comp)))

    for nid in ids:
        if nid not in index:
            strongconnect(nid)
    return cycles
