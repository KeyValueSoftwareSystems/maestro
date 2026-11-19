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
    "unreachable-node", "bad-placeholder", "undeclared-input",
    "parallel-too-few-branches", "branch-bad-start", "branch-bad-type",
    "subworkflow-missing-file", "subworkflow-too-deep", "subworkflow-cycle",
    "cycle-no-brake", "bad-max-visits", "artifact-not-string", "empty-instruction",
    "interview-no-sections", "interview-dup-sections", "interview-no-source",
    "interview-multiple-sources", "bad-batch-size", "say-style", "gate-pause-option",
]
SAY_MAX = 100  # a `say:` line is one short sentence the person reads

MAX_DEPTH = 4
RESERVED = ("end", "abort")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PLACEHOLDER_RE = re.compile(r"\$\{([^{}]+)\}")

_TOP_KEYS = {"version", "name", "title", "description", "inputs", "defaults", "start", "nodes", "outputs", "ui"}
_ROUTING_KEYS = {"next", "routes", "on_fail", "max_visits", "on_exhausted"}
_NODE_KEYS = {
    "agent": {"id", "type", "label", "say", "instruction", "skill", "agent", "model", "execution",
              "inputs", "outputs", "artifact", "fresh", "brief", "timeout", "retries", "check",
              "isolate", "ui"} | _ROUTING_KEYS,
    "interview": {"id", "type", "label", "say", "skill", "context", "sections",
                  "questions_artifact", "batch_size", "presentation", "discuss", "artifact", "auto",
                  "ui", "next",
                  "routes", "max_visits", "on_exhausted"},
    "gate": {"id", "type", "label", "say", "prompt", "options", "auto", "max_visits", "on_exhausted", "ui"},
    "script": {"id", "type", "label", "say", "run", "timeout", "ui"} | _ROUTING_KEYS,
    "parallel": {"id", "type", "label", "say", "join", "on_branch_fail", "branches", "isolate", "ui"} | _ROUTING_KEYS,
    "subworkflow": {"id", "type", "label", "say", "workflow", "inputs", "ui"} | _ROUTING_KEYS,
}
_BRANCH_NODE_TYPES = {"agent", "gate", "script", "subworkflow"}

# Field types and enums of each node type, mirroring workflow.schema.json. Kinds: str, nestr
# (non-empty string), bool, int1 / int0 (whole number >= 1 / >= 0), map, strlist, scalarmap
# (string -> string/number/boolean), or ("enum", values). Routing keys, `artifact`,
# `instruction`, `check`, `batch_size` and the structured fields have their own checks.
_COMMON_FIELDS = {"label": "str", "say": "str", "ui": "map"}
_FIELD_TYPES = {
    "agent": {"skill": "str", "agent": "str", "model": "str",
              "execution": ("enum", ("worker", "lead")), "inputs": "scalarmap",
              "outputs": "strlist", "fresh": "bool",
              "brief": ("enum", ("none", "minimal", "full")), "timeout": "int1",
              "retries": "int0", "isolate": ("enum", ("worktree",))},
    "interview": {"skill": "str", "context": "str",
                  "presentation": ("enum", ("chat", "popup"))},
    "gate": {"prompt": "nestr"},
    "script": {"timeout": "int1"},
    "parallel": {"join": ("enum", ("all", "any")),
                 "on_branch_fail": ("enum", ("fail_all", "continue", "ask")),
                 "isolate": ("enum", ("worktree",))},
    "subworkflow": {"inputs": "scalarmap"},
}
_DEFAULTS_KEYS = {"model", "agent", "max_visits", "brief"}
_INPUT_KEYS = {"type", "required", "default", "description", "enum"}
_INPUT_TYPES = ("string", "number", "boolean", "list")


def _is_int(value, minimum):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _kind_problem(kind, value):
    """-> what `value` should have been, or None when it fits `kind`."""
    if isinstance(kind, tuple):
        ok = isinstance(value, str) and value in kind[1]
        return None if ok else "one of " + ", ".join(kind[1])
    if kind == "str":
        return None if isinstance(value, str) else "a string"
    if kind == "nestr":
        return None if isinstance(value, str) and value.strip() else "a non-empty string"
    if kind == "bool":
        return None if isinstance(value, bool) else "true or false"
    if kind == "int1":
        return None if _is_int(value, 1) else "a positive whole number"
    if kind == "int0":
        return None if _is_int(value, 0) else "a whole number, 0 or more"
    if kind == "map":
        return None if isinstance(value, dict) else "a map"
    if kind == "strlist":
        ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
        return None if ok else "a list of strings"
    if kind == "scalarmap":
        ok = isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, (str, int, float, bool)) for k, v in value.items())
        return None if ok else "a map of strings to strings, numbers or booleans"
    return None


def _check_fields(node, ntype, err):
    fields = dict(_COMMON_FIELDS)
    fields.update(_FIELD_TYPES.get(ntype, {}))
    for key, kind in fields.items():
        if key in node:
            problem = _kind_problem(kind, node[key])
            if problem:
                err("bad-type", f"{ntype} {key} must be {problem}, got {node[key]!r}")


def _check_target(value, what, ids, err, words=RESERVED):
    """A route/option/failure target: a node id of this scope or one of `words`."""
    if not isinstance(value, str):
        err("bad-type", f"{what} must be a node id (a string), got {value!r}")
    elif value not in ids and value not in words:
        err("missing-route-target", f"{what} targets unknown node {value!r}")


def _ntype(node):
    """A node's type as a hashable string ('?' when it is not one)."""
    t = node.get("type", "agent") if isinstance(node, dict) else None
    return t if isinstance(t, str) else "?"


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
    except (OSError, ValueError) as exc:
        # ValueError covers wf.WfError and UnicodeDecodeError (non-UTF-8 workflow files).
        return [Issue("error", "bad-yaml", f"{norm}: {exc}")]
    issues.extend(validate_doc(doc, where=norm))

    # recurse into subworkflow files (top-level nodes and inside parallel branches)
    def sub_nodes(node_list):
        for node in node_list if isinstance(node_list, list) else []:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "subworkflow":
                yield node
            branches = node.get("branches")
            for branch in branches if isinstance(branches, list) else []:
                if isinstance(branch, dict):
                    yield from sub_nodes(branch.get("steps"))

    for node in sub_nodes(doc.get("nodes") if isinstance(doc, dict) else None):
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
    if "nodes" not in doc:
        err("missing-key", "missing required top-level key 'nodes'")
    if "version" in doc and (not _is_int(doc["version"], 1) or doc["version"] != 1):
        err("bad-version", f"unsupported version {doc['version']!r} (expected 1)")
    if "name" in doc and (not isinstance(doc["name"], str) or not _NAME_RE.match(doc["name"])):
        err("bad-name", f"name must be kebab-case: {doc.get('name')!r}")
    for key in ("title", "description"):
        if key in doc and not isinstance(doc[key], str):
            err("bad-type", f"{key} must be a string")
    if doc.get("start") is not None and not isinstance(doc["start"], str):
        err("bad-type", f"start must be a node id (a string), got {doc['start']!r}")
    # an empty `inputs:` / `defaults:` / `outputs:` / `ui:` (null) is the same as absent
    for key in ("inputs", "defaults", "outputs", "ui"):
        if doc.get(key) is not None and not isinstance(doc[key], dict):
            err("bad-type", f"{key} must be a map, got {doc[key]!r}")
    inputs = doc.get("inputs") if isinstance(doc.get("inputs"), dict) else {}
    for iname, spec in inputs.items():
        if not isinstance(spec, dict):
            err("bad-type", f"inputs.{iname} must be a map, got {spec!r}")
            continue
        for k in spec:
            if k not in _INPUT_KEYS:
                err("unknown-key", f"inputs.{iname} has unknown key {k!r}")
        if "type" in spec and (not isinstance(spec["type"], str) or spec["type"] not in _INPUT_TYPES):
            err("bad-type", f"inputs.{iname}.type must be one of {', '.join(_INPUT_TYPES)}")
        if "required" in spec and not isinstance(spec["required"], bool):
            err("bad-type", f"inputs.{iname}.required must be true or false")
        if "description" in spec and not isinstance(spec["description"], str):
            err("bad-type", f"inputs.{iname}.description must be a string")
        if "enum" in spec:
            allowed = spec["enum"]
            if not isinstance(allowed, list) or not allowed:
                err("bad-type", f"inputs.{iname}.enum must be a non-empty list of values")
            elif "default" in spec and isinstance(spec["default"], str) \
                    and "${" not in spec["default"] and spec["default"] not in allowed:
                err("bad-type", f"inputs.{iname}.default {spec['default']!r} is not one of "
                    f"its enum values")
    outputs = doc.get("outputs") if isinstance(doc.get("outputs"), dict) else {}
    for oname, oval in outputs.items():
        if not isinstance(oval, str):
            err("bad-type", f"outputs.{oname} must be a string, got {oval!r}")
    defaults = doc.get("defaults") if isinstance(doc.get("defaults"), dict) else {}
    for k in defaults:
        if k not in _DEFAULTS_KEYS:
            err("unknown-key", f"unknown defaults key {k!r}")
    for k in ("model", "agent"):
        if k in defaults and not isinstance(defaults[k], str):
            err("bad-type", f"defaults.{k} must be a string")
    if "brief" in defaults and (not isinstance(defaults["brief"], str)
                                or defaults["brief"] not in ("none", "minimal", "full")):
        err("bad-type", "defaults.brief must be 'none', 'minimal' or 'full'")
    if "max_visits" in defaults and not _is_int(defaults["max_visits"], 1):
        err("bad-max-visits",
            f"defaults.max_visits must be a positive integer, got {defaults['max_visits']!r}")

    declared_inputs = {k for k in inputs if isinstance(k, str)} | {"slug"}
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
    if start is None and nodes and isinstance(nodes[0], dict):
        start = nodes[0].get("id")  # minimal authoring: first node is the start
    if not isinstance(start, str):
        start = None  # a wrong-typed start was reported above
    if start is not None and start not in ids:
        err("no-start", f"start {start!r} is not a node id")

    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("id"), str) and node["id"] in ids:
            issues.extend(_validate_node(node, ids, declared_inputs, where))

    if start in ids:
        reachable = _reachable(ids, start)
        for nid in ids:
            if nid not in reachable:
                warn("unreachable-node", f"node {nid!r} is unreachable from start")
        for cyc in _find_cycles(ids):
            kinds = {_ntype(ids[n]) for n in cyc}
            # A subworkflow that routes on its child's reported outputs is a deterministic brake
            # too: the stage's own gates decide, the parent only acts on the recorded choice.
            routed_stage = any(_ntype(ids[n]) == "subworkflow" and ids[n].get("routes")
                               for n in cyc)
            if "gate" not in kinds and "script" not in kinds and not routed_stage:
                warn("cycle-no-brake",
                     f"cycle {' -> '.join(cyc)} contains no gate and no script — "
                     f"agent-only loops burn tokens with nothing deterministic to stop them")
    return issues


def _validate_auto(node, err, keys):
    """Check a gate's or interview's `auto:` autopilot policy. -> the policy map, or None."""
    auto = node.get("auto")
    if auto is None:
        return None
    kind = node.get("type")
    if not isinstance(auto, dict):
        err("bad-type", f"{kind} auto must be a map: {{{', '.join(keys)}}}")
        return None
    for k in auto:
        if k not in keys:
            err("unknown-key", f"{kind} auto has unknown key {k!r}")
    modes = auto.get("modes")
    if modes is not None and not (
            isinstance(modes, list) and modes and all(m in ("design", "auto") for m in modes)):
        err("bad-type", f"{kind} auto.modes must be a non-empty list of design/auto")
    conds = auto.get("when")
    if conds is not None:
        if isinstance(conds, str):
            conds = [conds]
        if not isinstance(conds, list) or not conds or not all(isinstance(c, str) for c in conds):
            err("bad-type", f"{kind} auto.when must be a condition or a list of conditions")
            conds = []
        for cond in conds:
            try:
                condctl.parse(cond)
            except condctl.CondError as exc:
                err("bad-condition", f"{kind} auto.when: {exc}")
    return auto


def _validate_node(node, ids, declared_inputs, where):
    issues = []
    nid = node["id"]
    w = f"{where}#{nid}" if where else nid
    err = lambda code, msg: issues.append(Issue("error", code, msg, w))
    warn = lambda code, msg: issues.append(Issue("warning", code, msg, w))

    ntype = node.get("type", "agent")
    if not isinstance(ntype, str) or ntype not in _NODE_KEYS:
        err("bad-type", f"unknown node type {ntype!r}")
        return issues
    for key in node:
        if key not in _NODE_KEYS[ntype]:
            err("unknown-key", f"{ntype} node has unknown key {key!r}")
    _check_fields(node, ntype, err)
    say = node.get("say")
    if isinstance(say, str):
        if len(say.strip()) > SAY_MAX:
            warn("say-style", f"say is {len(say.strip())} characters; keep it to one line of "
                              f"about {SAY_MAX}")
        if "${steps." in say or "\n" in say.strip():
            warn("say-style", "say is one plain line for the person: no ${steps.…} internals "
                              "and no line breaks")

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
        check = node.get("check")
        checks = check if isinstance(check, list) else [check]
        if check is not None and not checks:
            err("bad-type", "agent check list must not be empty")
        for item in checks if check is not None else []:
            if not isinstance(item, dict):
                err("bad-type", "agent check must be a map with `run`, or a list of them")
            else:
                for key in item:
                    if key not in ("run", "attempts", "timeout"):
                        err("unknown-key", f"agent check has unknown key {key!r}")
                run = item.get("run")
                if not (isinstance(run, list) and run and all(isinstance(a, str) for a in run)):
                    err("missing-key", "agent check needs `run`: a non-empty list of strings")
                for key in ("attempts", "timeout"):
                    if key in item and not _is_int(item[key], 1):
                        err("bad-type", f"agent check {key} must be a positive whole number")
    elif ntype == "interview":
        sections = node.get("sections")
        questions_artifact = node.get("questions_artifact")
        has_sections = isinstance(sections, list) and bool(sections)
        has_questions = isinstance(questions_artifact, str) and bool(questions_artifact.strip())
        if not has_sections and not has_questions:
            err("interview-no-source", "interview needs sections or questions_artifact")
        if has_sections and has_questions:
            err("interview-multiple-sources", "interview cannot use both sections and questions_artifact")
        if sections is not None and (not isinstance(sections, list) or not sections):
            err("interview-no-sections", "interview sections must be a non-empty list")
            sections = []
        elif sections is None:
            sections = []
        seen = set()
        for section in sections:
            if not isinstance(section, dict) or not all(k in section for k in ("id", "title")):
                err("missing-key", f"interview section must have id/title: {section!r}")
                continue
            sid = section["id"]
            if not isinstance(sid, str) or not _ID_RE.match(sid):
                err("bad-id", f"interview section has bad id {sid!r}")
            elif sid in seen:
                err("interview-dup-sections", f"duplicate interview section id {sid!r}")
            if isinstance(sid, str):
                seen.add(sid)
            if not isinstance(section["title"], str) or not section["title"].strip():
                err("bad-type", f"interview section {sid!r} title must be a non-empty string")
            for key in section:
                if key not in ("id", "title", "proposal", "prompt"):
                    err("unknown-key", f"interview section has unknown key {key!r}")
                elif key in ("proposal", "prompt") and not isinstance(section[key], str):
                    err("bad-type", f"interview section {sid!r} {key} must be a string")
        if not isinstance(node.get("artifact"), str) or not node.get("artifact"):
            err("artifact-not-string", "interview artifact must be a non-empty string")
        if questions_artifact is not None and not has_questions:
            err("artifact-not-string", "questions_artifact must be a non-empty string")
        batch_size = node.get("batch_size", 1)
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            err("bad-batch-size", "interview batch_size must be a positive integer")
        discuss = node.get("discuss")
        if discuss is not None:
            if not isinstance(discuss, dict):
                err("bad-type", "interview discuss must be a map")
            else:
                for key in discuss:
                    if key not in ("inputs", "agent", "model"):
                        err("unknown-key", f"interview discuss has unknown key {key!r}")
                if not isinstance(discuss.get("inputs", {}), dict):
                    err("bad-type", "interview discuss.inputs must be a map")
                for key in ("agent", "model"):
                    if key in discuss and not isinstance(discuss[key], str):
                        err("bad-type", f"interview discuss.{key} must be a string")
        _validate_auto(node, err, keys=("modes", "when"))
    elif ntype == "gate":
        options = node.get("options")
        if not isinstance(options, list) or not options:
            err("gate-no-options", "gate needs at least one option")
            options = []
        seen = set()
        for opt in options:
            pause = isinstance(opt, dict) and opt.get("pause") is True
            if isinstance(opt, dict) and "pause" in opt and not isinstance(opt["pause"], bool):
                err("bad-type", f"gate option {opt.get('id')!r} pause must be true or false")
            needed = ("id", "label") if pause else ("id", "label", "to")
            if not isinstance(opt, dict) or not all(k in opt for k in needed):
                err("missing-key", f"gate option must have id/label/to: {opt!r}")
                continue
            if pause and ("to" in opt or "input" in opt):
                # the person answers later: the run stops here and takes no route
                err("gate-pause-option", f"gate option {opt['id']!r} pauses the run, so it "
                                         "takes no `to` or `input`")
            if not isinstance(opt["id"], str):
                err("bad-type", f"gate option id must be a string, got {opt['id']!r}")
            elif opt["id"] in seen:
                err("gate-dup-options", f"duplicate option id {opt['id']!r}")
            else:
                seen.add(opt["id"])
            if not isinstance(opt["label"], str):
                err("bad-type", f"gate option {opt['id']!r} label must be a string")
            if "input" in opt and not isinstance(opt["input"], str):
                err("bad-type", f"gate option {opt['id']!r} input must be a string")
            if not pause:
                _check_target(opt["to"], f"option {opt['id']!r}", ids, err)
            for k in opt:
                if k not in ("id", "label", "to", "input", "pause"):
                    err("unknown-key", f"gate option has unknown key {k!r}")
        auto = _validate_auto(node, err, keys=("option", "modes", "when"))
        if auto is not None and not isinstance(auto.get("option"), str):
            err("bad-type", f"gate auto.option must be an option id (a string), got "
                            f"{auto.get('option')!r}")
        elif auto is not None:
            picked = next((o for o in options if isinstance(o, dict)
                           and o.get("id") == auto.get("option")), None)
            if picked is None:
                err("missing-key", f"gate auto.option {auto.get('option')!r} is not an option")
            elif picked.get("pause"):
                err("gate-pause-option", f"gate auto.option {picked['id']!r} pauses the run; "
                                         "autopilot never pauses")
            elif picked.get("input") or picked.get("to") == "abort":
                # autopilot has no text to give and never ends a run on its own
                err("bad-type", f"gate auto.option {picked['id']!r} must not need input "
                                "or abort")
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
            if not isinstance(branch["id"], str) or not _ID_RE.match(branch["id"]):
                err("bad-id", f"bad branch id {branch['id']!r}")
                continue
            if branch["id"] in bids:
                err("dup-id", f"duplicate branch id {branch['id']!r}")
            bids.add(branch["id"])
            for key in branch:
                if key not in ("id", "start", "steps", "ui"):
                    err("unknown-key", f"branch {branch['id']} has unknown key {key!r}")
            if "ui" in branch and not isinstance(branch["ui"], dict):
                err("bad-type", f"branch {branch['id']}: ui must be a map")
            steps = branch.get("steps")
            if not isinstance(steps, list) or not steps:
                err("bad-type", f"branch {branch['id']}: steps must be a non-empty list")
                steps = []
            bids_map = {}
            for step in steps:
                if not isinstance(step, dict):
                    err("bad-type", f"branch {branch['id']}: steps must be mappings")
                    continue
                if _ntype(step) not in _BRANCH_NODE_TYPES:
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
            if not isinstance(branch.get("start"), str) or branch["start"] not in bids_map:
                err("branch-bad-start", f"branch {branch['id']}: start {branch.get('start')!r} not in steps")
            for step in steps:
                if (isinstance(step, dict) and isinstance(step.get("id"), str)
                        and step["id"] in bids_map and _ntype(step) in _BRANCH_NODE_TYPES):
                    issues.extend(_validate_node(step, bids_map, declared_inputs, f"{w}[{branch['id']}]"))
    elif ntype == "subworkflow":
        if not isinstance(node.get("workflow"), str):
            err("missing-key", "subworkflow needs a workflow file path")

    # routing
    if ntype != "gate":
        has_next, has_routes = "next" in node, "routes" in node
        if has_next and has_routes:
            err("route-and-next", "use either next or routes, not both")
        # neither set = implicit `next: end` (minimal authoring)
        if has_next:
            _check_target(node["next"], "next", ids, err)
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
                _check_target(route["to"], f"routes[{i}]", ids, err)
                for k in route:
                    if k not in ("when", "to"):
                        err("unknown-key", f"routes[{i}] has unknown key {k!r}")
                cond = route.get("when")
                if cond is not None and not isinstance(cond, str):
                    err("bad-type", f"routes[{i}] when must be a condition string, got {cond!r}")
                elif cond in (None, ""):
                    default_seen = True
                    if i != len(routes) - 1:
                        err("no-default-route", "the default route (no when) must be last")
                else:
                    try:
                        condctl.parse(cond)
                        # The RHS of a comparison is a literal — never substituted. A
                        # placeholder there silently never matches; flag it early.
                        rhs = re.search(r"(?:==|!=|\bin\b)(.*)$", str(cond))
                        if rhs and "${" in rhs.group(1):
                            err("bad-condition",
                                f"right-hand side of a condition is a literal, not a "
                                f"placeholder — {cond!r} will never match as written")
                    except condctl.CondError as exc:
                        err("bad-condition", str(exc))
            if not default_seen:
                err("no-default-route", "routes need a final default entry with no when")
    for key in ("on_fail", "on_exhausted"):
        if key in node:
            _check_target(node[key], key, ids, err, words=("abort", "ask"))
    mv = node.get("max_visits")
    if "max_visits" in node and not _is_int(mv, 1) and not (
        isinstance(mv, str) and _PLACEHOLDER_RE.search(mv)
    ):
        issues.append(Issue("error", "bad-max-visits", f"max_visits must be a positive integer", w))

    # static placeholder checks over every string in the node; a parallel node's branch steps
    # were checked above against their own branch's ids, not this scope's
    for text in _strings({k: v for k, v in node.items() if k != "branches"}):
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
            elif parts[0] == "config" or parts == ["run", "mode"]:
                pass
            elif parts[0] == "memory":
                if not (len(parts) == 3 and parts[1] == "knowledge"):
                    issues.append(Issue("error", "bad-placeholder",
                                        f"memory ref must be ${{memory.knowledge.<domain>}}: ${{{ref}}}", w))
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
    routes = node.get("routes")
    for route in routes if isinstance(routes, list) else []:
        if isinstance(route, dict) and isinstance(route.get("to"), str):
            targets.append(route["to"])
    options = node.get("options")
    for option in options if isinstance(options, list) else []:
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
