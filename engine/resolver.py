"""The deterministic next-action resolver — the heart of Maestro v2.

The lead agent never interprets the workflow graph: this module reads workflow.yaml plus
the state ledger and serves exactly ONE next action as JSON (`next_action`), and applies
every state transition (`complete_step` / `record_gate` / `fail_step`). Routing,
placeholder substitution, visit caps, back-edge cascade resets, parallel joins and
subworkflow nesting all happen here, in plain Python, testable without any LLM.

Path ids: top-level node `author_hld`; inside subworkflow node `design` →
`design/author_hld`; inside branch `backend` of parallel node `author_llds` →
`author_llds[backend]/backend_design`.
"""

from __future__ import annotations

import json
import os
import re

try:
    import condctl
    import state as statemod
    import wf
except ImportError:  # imported as a package (tests)
    from . import condctl, state as statemod, wf


class RunError(RuntimeError):
    """Engine-level failure with a CLI exit code."""

    def __init__(self, msg, code=2):
        self.code = code
        super().__init__(msg)


DEFAULT_MAX_VISITS = 10
DEFAULT_SCRIPT_TIMEOUT = 300
RESERVED_TARGETS = ("end", "abort")


def ntype(node):
    """Node type with the minimal-authoring default: no `type:` means agent."""
    return node.get("type", "agent")


def wf_start(workflow):
    """`start:` is optional — default to the first node."""
    start = workflow.get("start")
    if start:
        return start
    nodes = workflow.get("nodes") or []
    return nodes[0]["id"] if nodes else None

_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")


# ---------------------------------------------------------------- frames

class Frame:
    """Where a node lives: the main workflow, a subworkflow, or a parallel branch."""

    __slots__ = ("kind", "prefix", "workflow", "nodes", "start", "inputs", "parent", "parent_node")

    def __init__(self, kind, prefix, workflow, nodes, start, inputs, parent=None, parent_node=None):
        self.kind = kind              # 'main' | 'sub' | 'branch'
        self.prefix = prefix          # '' or 'design/' or 'author_llds[backend]/'
        self.workflow = workflow      # owning workflow dict (branch: the parent's)
        self.nodes = nodes            # id -> node dict
        self.start = start
        self.inputs = inputs
        self.parent = parent
        self.parent_node = parent_node  # the subworkflow/parallel node in the parent frame

    def path(self, node_id):
        return self.prefix + node_id


def _nodes_by_id(node_list):
    return {n["id"]: n for n in node_list}


class Run:
    """A loaded run: workflows + state + config, with frame bookkeeping."""

    def __init__(self, slug, root=".", state_data=None):
        self.slug = slug
        self.root = root
        self.config = _load_config(root)
        self.state = state_data if state_data is not None else statemod.load(slug, root)
        if self.state is None:
            raise RunError(f"no run found for slug {slug!r} — run `init` first", code=3)
        self._wf_cache = {}

    # -- workflow loading ------------------------------------------------

    def load_workflow(self, rel_path, expect_hash=None):
        if rel_path not in self._wf_cache:
            full = os.path.join(self.root, rel_path)
            if not os.path.exists(full):
                raise RunError(f"workflow file missing: {rel_path}", code=3)
            if expect_hash is not None:
                actual = statemod.sha256_file(full)
                if actual != expect_hash:
                    raise RunError(
                        f"workflow file {rel_path} changed since this run started "
                        f"(sha256 mismatch). Run `maestroctl rebase --slug {self.slug}` to "
                        f"accept the edit, or `reset --all` to start over.",
                        code=3,
                    )
            self._wf_cache[rel_path] = wf.load_file(full)
        return self._wf_cache[rel_path]

    def main_frame(self):
        info = self.state["workflow"]
        workflow = self.load_workflow(info["file"], info.get("sha256"))
        return Frame(
            "main", "", workflow, _nodes_by_id(workflow["nodes"]), wf_start(workflow),
            self.state["inputs"],
        )

    def frame_for(self, path):
        """Resolve the frame that owns the FINAL segment of `path`."""
        frame = self.main_frame()
        segments = path.split("/")
        for seg in segments[:-1]:
            m = re.match(r"^([a-z0-9_-]+)\[([a-z0-9_-]+)\]$", seg)
            if m:  # parallel branch segment
                node = frame.nodes.get(m.group(1))
                if not node or ntype(node) != "parallel":
                    raise RunError(f"bad path {path!r}: {seg!r} is not a parallel node")
                branch = _find_branch(node, m.group(2))
                frame = Frame(
                    "branch", frame.prefix + seg + "/", frame.workflow,
                    _nodes_by_id(branch["steps"]), branch["start"], frame.inputs,
                    parent=frame, parent_node=node,
                )
            else:  # subworkflow segment
                node = frame.nodes.get(seg)
                if not node or ntype(node) != "subworkflow":
                    raise RunError(f"bad path {path!r}: {seg!r} is not a subworkflow node")
                frame = self._sub_frame(frame, node)
        return frame

    def _sub_frame(self, parent, node):
        path = parent.path(node["id"])
        info = self.state["frames"].get(path)
        if info is None:
            raise RunError(f"subworkflow {path!r} was never entered")
        child = self.load_workflow(info["workflow"], info.get("sha256"))
        return Frame(
            "sub", path + "/", child, _nodes_by_id(child["nodes"]), wf_start(child),
            info.get("inputs", {}), parent=parent, parent_node=node,
        )

    def node_at(self, path):
        frame = self.frame_for(path)
        node_id = path.split("/")[-1]
        node = frame.nodes.get(node_id)
        if node is None:
            raise RunError(f"unknown step {path!r}")
        return frame, node

    # -- placeholder resolution -------------------------------------------

    def resolve_text(self, text, frame, missing_ok=False):
        def repl(m):
            value = self.resolve_ref(m.group(1).strip(), frame, missing_ok)
            if value is None:
                return ""
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, (list, dict)):
                return json.dumps(value)
            return str(value)

        return _PLACEHOLDER_RE.sub(repl, str(text))

    def resolve_ref(self, ref, frame, missing_ok=False):
        parts = ref.split(".")
        try:
            if parts[0] == "inputs" and len(parts) == 2:
                f = frame
                while f is not None:
                    if parts[1] in f.inputs:
                        return f.inputs[parts[1]]
                    f = f.parent if f.kind == "branch" else None
                raise KeyError(ref)
            if parts[0] == "config":
                value = self.config
                for p in parts[1:]:
                    value = value[p]
                return value
            if parts[0] == "steps" and len(parts) >= 3:
                step_id = parts[1]
                entry = self._lookup_step(step_id, frame)
                if entry is None:
                    raise KeyError(ref)
                if parts[2] == "outputs" and len(parts) == 4:
                    return entry.get("outputs", {})[parts[3]]
                if parts[2] == "branches" and len(parts) == 6 and parts[4] == "outputs":
                    return entry.get("branches", {})[parts[3]].get("outputs", {})[parts[5]]
                raise KeyError(ref)
            raise KeyError(ref)
        except (KeyError, IndexError, TypeError):
            if missing_ok:
                return None
            raise RunError(f"unresolvable placeholder ${{{ref}}}", code=4) from None

    def _lookup_step(self, step_id, frame):
        f = frame
        while f is not None:
            entry = self.state["steps"].get(f.prefix + step_id)
            if entry is not None:
                return entry
            f = f.parent
        return self.state["steps"].get(step_id)

    def resolve_value(self, value, frame, missing_ok=False):
        if isinstance(value, str):
            m = _PLACEHOLDER_RE.fullmatch(value.strip())
            if m:  # a bare placeholder keeps its native type (lists, numbers…)
                return self.resolve_ref(m.group(1).strip(), frame, missing_ok)
            return self.resolve_text(value, frame, missing_ok)
        return value

    # -- config helpers ----------------------------------------------------

    def defaults(self, frame, key, fallback=None):
        value = (frame.workflow.get("defaults") or {}).get(key)
        if value is None:
            value = ((self.config.get("defaults") or {}).get(key))
        return fallback if value is None else value

    def model_for(self, node, frame):
        raw = node.get("model") or self.defaults(frame, "model") or (
            (self.config.get("models") or {}).get("default")
        ) or "haiku"
        raw = self.resolve_text(raw, frame)
        aliases = (self.config.get("models") or {}).get("aliases") or {}
        return aliases.get(raw, raw)

    def agent_for(self, node, frame):
        return node.get("agent") or self.defaults(frame, "agent") or "general"

    def max_visits_for(self, node, frame):
        raw = node.get("max_visits")
        if raw is None:
            raw = self.defaults(frame, "max_visits", DEFAULT_MAX_VISITS)
        if isinstance(raw, str):
            raw = int(self.resolve_text(raw, frame))
        return int(raw)


def _load_config(root):
    for name in ("maestro.config.yaml",):
        path = os.path.join(root, name)
        if os.path.exists(path):
            return wf.load_file(path) or {}
    return {}


def _find_branch(node, branch_id):
    for b in node.get("branches", []):
        if b["id"] == branch_id:
            return b
    raise RunError(f"parallel node {node['id']!r} has no branch {branch_id!r}")


# ---------------------------------------------------------------- init

def coerce_input(declared, raw):
    kind = (declared or {}).get("type", "string")
    if kind == "number":
        return float(raw) if "." in str(raw) else int(raw)
    if kind == "boolean":
        return str(raw).lower() in ("1", "true", "yes")
    if kind == "list":
        if isinstance(raw, list):
            return raw
        raw = str(raw)
        if raw.startswith("["):
            return json.loads(raw)
        return [p.strip() for p in raw.split(",") if p.strip()]
    return raw


def init_run(slug, workflow_file, inputs, root=".", force=False):
    """Create (or no-op onto) the run ledger. Returns (state, created?)."""
    full = os.path.join(root, workflow_file)
    if not os.path.exists(full):
        raise RunError(f"workflow file not found: {workflow_file}", code=3)
    digest = statemod.sha256_file(full)
    existing = statemod.load(slug, root)
    if existing is not None and not force:
        if existing["workflow"]["file"] != workflow_file:
            raise RunError(
                f"slug {slug!r} already runs {existing['workflow']['file']}; "
                f"pass --force to restart with {workflow_file}", code=3,
            )
        if existing["workflow"].get("sha256") != digest:
            raise RunError(
                f"workflow {workflow_file} changed since this run started. "
                f"`maestroctl rebase --slug {slug}` accepts the edit; --force restarts.",
                code=3,
            )
        return existing, False

    workflow = wf.load_file(full)
    declared = workflow.get("inputs") or {}
    resolved = {"slug": slug}
    resolved.update(inputs)
    for name, spec in declared.items():
        if name in resolved:
            resolved[name] = coerce_input(spec, resolved[name])
        elif spec and spec.get("required"):
            raise RunError(f"missing required input {name!r}", code=3)
    # defaults may reference other inputs; resolve in declaration order
    for name, spec in declared.items():
        if name not in resolved and spec and "default" in spec:
            default = spec["default"]
            if isinstance(default, str):
                def repl(m, res=resolved):
                    ref = m.group(1).strip()
                    if ref.startswith("inputs.") and ref[7:] in res:
                        return str(res[ref[7:]])
                    return m.group(0)
                default = _PLACEHOLDER_RE.sub(repl, default)
            resolved[name] = coerce_input(spec, default)

    data = statemod.new_state(slug, workflow_file, digest, resolved)
    run = Run(slug, root, state_data=data)
    frame = run.main_frame()
    _enter(run, frame, wf_start(workflow))
    statemod.save(slug, data, root)
    return data, True


# ---------------------------------------------------------------- entering nodes

def _cursors(run):
    return run.state["run"]["cursors"]


def _add_cursor(run, path):
    if path not in _cursors(run):
        _cursors(run).append(path)


def _drop_cursor(run, path):
    with_out = [c for c in _cursors(run) if c != path]
    run.state["run"]["cursors"][:] = with_out


def _enter(run, frame, node_id, via_gate=False):
    """Move execution onto `node_id` in `frame` (visit caps + re-entry reset apply).

    via_gate: the human explicitly routed here through a real gate option — the visit
    still counts, but the cap does not block (the human is the loop bound).
    """
    node = frame.nodes.get(node_id)
    if node is None:
        raise RunError(f"route target {node_id!r} not found in {frame.prefix or 'main'}")
    path = frame.path(node_id)
    entry = statemod.step_entry(run.state, path)
    entry["visits"] = entry.get("visits", 0) + 1
    cap = run.max_visits_for(node, frame)
    if entry["visits"] > cap and not via_gate:
        target = node.get("on_exhausted", "ask")
        if target == "abort":
            _frame_abort(run, frame, reason=f"{path}: visit cap {cap} exhausted")
        elif target == "ask":
            entry["pending_ask"] = {"kind": "exhausted", "reason": f"visit cap {cap} reached"}
            entry["status"] = "pending"
            _add_cursor(run, path)
        else:
            _enter(run, frame, target)
        return
    if entry.get("status") in ("done", "failed", "skipped"):
        _cascade_reset(run, frame, node_id)
        entry = statemod.step_entry(run.state, path)
        entry["visits"] = entry.get("visits", 0)  # preserved by reset
    _enter_inner(run, frame, node)


def _enter_inner(run, frame, node):
    path = frame.path(node["id"])
    entry = statemod.step_entry(run.state, path)
    kind = ntype(node)
    if kind == "parallel":
        entry["status"] = "running"
        entry["branches"] = {b["id"]: {"status": "running"} for b in node["branches"]}
        for branch in node["branches"]:
            bframe = Frame(
                "branch", frame.prefix + f"{node['id']}[{branch['id']}]/", frame.workflow,
                _nodes_by_id(branch["steps"]), branch["start"], frame.inputs,
                parent=frame, parent_node=node,
            )
            _enter(run, bframe, branch["start"])
    elif kind == "subworkflow":
        rel = node["workflow"]
        full = os.path.join(run.root, rel)
        if not os.path.exists(full):
            raise RunError(f"subworkflow file missing: {rel}", code=3)
        child_inputs = {
            k: run.resolve_value(v, frame) for k, v in (node.get("inputs") or {}).items()
        }
        child_inputs.setdefault("slug", run.state["inputs"].get("slug", run.slug))
        run.state["frames"][path] = {
            "workflow": rel, "sha256": statemod.sha256_file(full), "inputs": child_inputs,
        }
        run._wf_cache.pop(rel, None)
        entry["status"] = "running"
        child_frame = run._sub_frame(frame, node)
        # apply child input declarations (defaults / required)
        declared = child_frame.workflow.get("inputs") or {}
        for name, spec in declared.items():
            if name in child_inputs:
                child_inputs[name] = coerce_input(spec, child_inputs[name])
            elif spec and spec.get("required"):
                raise RunError(f"subworkflow {rel}: missing required input {name!r}", code=4)
            elif spec and "default" in spec:
                default = spec["default"]
                if isinstance(default, str):
                    def repl(m, res=child_inputs):
                        ref = m.group(1).strip()
                        if ref.startswith("inputs.") and ref[7:] in res:
                            return str(res[ref[7:]])
                        return m.group(0)
                    default = _PLACEHOLDER_RE.sub(repl, default)
                child_inputs[name] = coerce_input(spec, default)
        _enter(run, child_frame, child_frame.start)
    else:
        entry["status"] = "pending"
        _add_cursor(run, path)


# ---------------------------------------------------------------- reset

def _frame_edges(node):
    """Outgoing edge targets of a node within its frame (excludes end/abort)."""
    targets = []
    if node.get("next"):
        targets.append(node["next"])
    for route in node.get("routes") or []:
        targets.append(route["to"])
    for option in node.get("options") or []:
        targets.append(option["to"])
    for key in ("on_fail", "on_exhausted"):
        value = node.get(key)
        if value and value not in ("abort", "ask"):
            targets.append(value)
    return [t for t in targets if t not in RESERVED_TARGETS]


def _reachable(frame, start_id):
    seen, stack = set(), [start_id]
    while stack:
        nid = stack.pop()
        if nid in seen or nid not in frame.nodes:
            continue
        seen.add(nid)
        stack.extend(_frame_edges(frame.nodes[nid]))
    return seen


def _reset_step(run, frame, node_id):
    path = frame.path(node_id)
    entry = run.state["steps"].get(path)
    if entry is None:
        return
    visits = entry.get("visits", 0)
    run.state["steps"][path] = {"status": "pending", "attempts": 0, "visits": visits, "outputs": {}}
    # wipe nested state (subworkflow children / branch steps)
    for key in list(run.state["steps"]):
        if key.startswith(path + "/") or key.startswith(path + "["):
            del run.state["steps"][key]
    for key in list(run.state["frames"]):
        if key == path or key.startswith(path + "/") or key.startswith(path + "["):
            del run.state["frames"][key]
    _drop_cursor(run, path)
    for cursor in list(_cursors(run)):
        if cursor.startswith(path + "/") or cursor.startswith(path + "["):
            _drop_cursor(run, cursor)


def _cascade_reset(run, frame, node_id):
    """Re-entry reset: the target plus every terminal-status step reachable from it."""
    for nid in _reachable(frame, node_id):
        path = frame.path(nid)
        entry = run.state["steps"].get(path)
        if nid == node_id or (entry and entry.get("status") in ("done", "failed", "skipped")):
            _reset_step(run, frame, nid)


# ---------------------------------------------------------------- advancing

def _default_target(node):
    if node.get("next"):
        return node["next"]
    routes = node.get("routes") or []
    for route in reversed(routes):
        if "when" not in route or route.get("when") in (None, ""):
            return route["to"]
    return None if routes else "end"  # no routing at all = implicit end


def _route_target(run, frame, node):
    if node.get("next"):
        return node["next"]
    routes = node.get("routes") or []
    if not routes:
        return "end"  # minimal authoring: omitted routing ends the workflow (or branch)
    for route in routes:
        cond = route.get("when")
        if cond in (None, ""):
            return route["to"]
        if condctl.evaluate(cond, lambda text: run.resolve_text(text, frame, missing_ok=True)):
            return route["to"]
    raise RunError(f"node {frame.path(node['id'])!r}: no route matched and no default route", code=4)


def _advance(run, frame, node, last_outputs=None):
    """Route away from a completed node."""
    target = _route_target(run, frame, node)
    _leave_to(run, frame, node, target, last_outputs)


def _leave_to(run, frame, node, target, last_outputs=None, via_gate=False):
    _drop_cursor(run, frame.path(node["id"]))
    if target == "end":
        _frame_end(run, frame, last_outputs or {})
    elif target == "abort":
        _frame_abort(run, frame, reason=f"aborted at {frame.path(node['id'])}")
    else:
        _enter(run, frame, target, via_gate=via_gate)


def _frame_end(run, frame, last_outputs):
    if frame.kind == "main":
        run.state["run"]["status"] = "done"
        run.state["run"]["cursors"] = []
        outputs = {}
        for key, value in (frame.workflow.get("outputs") or {}).items():
            outputs[key] = run.resolve_value(value, frame, missing_ok=True)
        run.state["run"]["outputs"] = outputs
    elif frame.kind == "sub":
        node = frame.parent_node
        path = frame.parent.path(node["id"])
        entry = statemod.step_entry(run.state, path)
        outputs = {}
        for key, value in (frame.workflow.get("outputs") or {}).items():
            outputs[key] = run.resolve_value(value, frame, missing_ok=True)
        entry["outputs"] = outputs
        entry["status"] = "done"
        _advance(run, frame.parent, node, outputs)
    else:  # branch
        _branch_terminal(run, frame, "done", last_outputs)


def _frame_abort(run, frame, reason):
    if frame.kind == "main":
        run.state["run"]["status"] = "failed"
        run.state["run"]["reason"] = reason
        run.state["run"]["cursors"] = []
    elif frame.kind == "sub":
        node = frame.parent_node
        path = frame.parent.path(node["id"])
        entry = statemod.step_entry(run.state, path)
        entry["status"] = "failed"
        entry["reason"] = reason
        _apply_on_fail(run, frame.parent, node, reason)
    else:
        _branch_terminal(run, frame, "failed", {}, reason)


def _branch_terminal(run, frame, status, outputs, reason=None):
    node = frame.parent_node
    parent = frame.parent
    ppath = parent.path(node["id"])
    entry = statemod.step_entry(run.state, ppath)
    branch_id = frame.prefix[:-1].rsplit("[", 1)[1][:-1]
    record = {"status": status, "outputs": outputs or {}}
    if reason:
        record["reason"] = reason
    entry.setdefault("branches", {})[branch_id] = record

    mode = node.get("on_branch_fail", "fail_all")
    if status == "failed":
        if mode == "fail_all":
            entry["status"] = "failed"
            entry["reason"] = f"branch {branch_id} failed: {reason or 'aborted'}"
            _cancel_branches(run, parent, node)
            _apply_on_fail(run, parent, node, entry["reason"])
            return
        if mode == "ask":
            entry["pending_ask"] = {
                "kind": "branch_fail", "branch": branch_id,
                "reason": reason or f"branch {branch_id} failed",
            }
            _add_cursor(run, ppath)
            return
        # continue: fall through to join accounting

    join = node.get("join", "all")
    branches = entry.get("branches", {})
    terminal = {b: r for b, r in branches.items() if r.get("status") in ("done", "failed", "skipped")}
    if join == "any" and status == "done":
        _cancel_branches(run, parent, node, keep=branch_id)
        entry["status"] = "done"
        _advance(run, parent, node)
        return
    if len(terminal) == len(node.get("branches", [])):
        if join == "any" and not any(r.get("status") == "done" for r in terminal.values()):
            entry["status"] = "failed"
            entry["reason"] = "no branch completed"
            _apply_on_fail(run, parent, node, entry["reason"])
            return
        entry["status"] = "done"
        _advance(run, parent, node)


def _cancel_branches(run, parent, node, keep=None):
    ppath = parent.path(node["id"])
    entry = statemod.step_entry(run.state, ppath)
    for branch in node.get("branches", []):
        bid = branch["id"]
        if bid == keep:
            continue
        record = entry.setdefault("branches", {}).setdefault(bid, {"status": "running"})
        if record.get("status") == "running":
            record["status"] = "cancelled"
        prefix = ppath + f"[{bid}]/"
        for cursor in list(_cursors(run)):
            if cursor.startswith(prefix):
                _drop_cursor(run, cursor)


def _apply_on_fail(run, frame, node, reason):
    path = frame.path(node["id"])
    entry = statemod.step_entry(run.state, path)
    target = node.get("on_fail", "ask")
    _drop_cursor(run, path)
    if target == "abort":
        _frame_abort(run, frame, reason)
    elif target == "ask":
        entry["pending_ask"] = {"kind": "fail", "reason": reason}
        _add_cursor(run, path)
    else:
        _enter(run, frame, target)


# ---------------------------------------------------------------- actions (read-only)

def next_action(run, serial=False):
    status = run.state["run"].get("status")
    if status == "done":
        return {
            "action": "done",
            "outputs": run.state["run"].get("outputs", {}),
            "summary": f"workflow {run.state['workflow']['file']} completed for {run.slug}",
        }
    if status == "failed":
        return {"action": "failed", "reason": run.state["run"].get("reason", "aborted")}
    cursors = list(_cursors(run))
    if not cursors:
        return {"action": "failed", "reason": "no active steps (inconsistent state) — reset the run"}

    gates, scripts, agents = [], [], []
    for path in cursors:
        frame, node = run.node_at(path)
        entry = statemod.step_entry(run.state, path)
        if entry.get("pending_ask"):
            gates.append(_synth_gate_action(run, path, node, entry))
        elif ntype(node) == "gate":
            gates.append(_gate_action(run, frame, node, path))
        elif ntype(node) == "script":
            scripts.append(_script_action(run, frame, node, path))
        elif ntype(node) == "agent":
            agents.append(_agent_action(run, frame, node, path))
        else:
            raise RunError(f"unexpected {ntype(node)} node in cursors: {path}")

    if scripts:
        return scripts[0]
    if gates:
        return gates[0]
    if len(agents) > 1 and not serial:
        return {"action": "run_agents", "agents": agents}
    if agents:
        return agents[0]
    return {"action": "failed", "reason": "nothing runnable — reset the run"}


def _script_action(run, frame, node, path):
    # missing_ok: argv may reference gate outputs that only exist for some options
    # (e.g. oq_record's answer text) — a missing ref becomes an empty argument
    argv = [run.resolve_text(a, frame, missing_ok=True) for a in node["run"]]
    return {
        "action": "run_script",
        "step": path,
        "argv": argv,
        "timeout": node.get("timeout", DEFAULT_SCRIPT_TIMEOUT),
    }


def _gate_action(run, frame, node, path):
    options = [
        {"id": o["id"], "label": o["label"], **({"input": o["input"]} if o.get("input") else {})}
        for o in node["options"]
    ]
    return {
        "action": "ask_gate",
        "step": path,
        "prompt": run.resolve_text(node["prompt"], frame, missing_ok=True),
        "options": options,
    }


def _synth_gate_action(run, path, node, entry):
    ask = entry["pending_ask"]
    if ask["kind"] == "fail":
        options = [
            {"id": "retry", "label": "Retry this step"},
            {"id": "skip", "label": "Skip this step and continue"},
            {"id": "abort", "label": "Abort the run"},
        ]
        prompt = f"Step `{path}` failed: {ask.get('reason', 'unknown error')}. How should we proceed?"
    elif ask["kind"] == "exhausted":
        options = [
            {"id": "continue", "label": "Run it once more anyway"},
            {"id": "abort", "label": "Abort the run"},
        ]
        prompt = f"Step `{path}` hit its repeat limit ({ask.get('reason')}). Continue anyway?"
    else:  # branch_fail
        options = [
            {"id": "retry", "label": f"Retry branch {ask['branch']}"},
            {"id": "skip", "label": f"Skip branch {ask['branch']} and continue"},
            {"id": "abort", "label": "Abort the run"},
        ]
        prompt = f"Branch `{ask['branch']}` of `{path}` failed: {ask.get('reason')}. How should we proceed?"
    return {"action": "ask_gate", "step": path, "prompt": prompt, "options": options,
            "synthesized": ask["kind"]}


def _agent_action(run, frame, node, path):
    resolved_inputs = {
        k: run.resolve_value(v, frame, missing_ok=True) for k, v in (node.get("inputs") or {}).items()
    }
    artifacts = _artifact_list(run, frame, node)
    isolate = node.get("isolate") or (
        frame.parent_node.get("isolate") if frame.kind == "branch" and frame.parent_node else None
    )
    skill = node.get("skill")
    if skill:
        skill = run.resolve_text(skill, frame)  # e.g. skill: "${inputs.stack}-implement"
    return {
        "action": "run_agent",
        "step": path,
        "agent_type": run.agent_for(node, frame),
        "model": run.model_for(node, frame),
        "skill": skill,
        "isolate": isolate,
        "outputs": node.get("outputs") or [],
        "artifacts": artifacts,
        "prompt": render_agent_prompt(run, frame, node, resolved_inputs, artifacts, isolate),
    }


def _artifact_list(run, frame, node):
    raw = node.get("artifact")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    return [run.resolve_text(a, frame) for a in items]


def render_agent_prompt(run, frame, node, inputs, artifacts, isolate):
    instruction = run.resolve_text(node["instruction"], frame, missing_ok=True)
    lines = [instruction.strip(), ""]
    if inputs:
        lines.append("Inputs:")
        for key, value in inputs.items():
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            lines.append(f"- {key}: {value}")
        lines.append("")
    skill = node.get("skill")
    if skill:
        lines.append(
            f"Load and follow the skill `{skill}` (skills/{skill}/SKILL.md) to perform this task. "
            f"Read it fully before acting; it owns the method and quality bar."
        )
    else:
        lines.append(
            "If an installed skill matches this task, load and follow it; otherwise proceed "
            "with your own best method."
        )
    if isolate == "worktree":
        slug = run.state["inputs"].get("slug", run.slug)
        lines.append(
            f"Work in an isolated git worktree on branch `maestro/{slug}/{node['id']}` "
            f"(create it if needed) so parallel steps cannot conflict. Commit your work there; "
            f"do NOT touch the main working tree."
        )
    if artifacts:
        lines.append("")
        lines.append("You MUST create the following file(s), non-empty, before returning:")
        for a in artifacts:
            lines.append(f"- {a}")
    lines.append("")
    fields = node.get("outputs") or []
    if fields:
        shape = ", ".join(f'"{f}": "..."' for f in fields)
        lines.append(
            f"Your reply's LAST line must be exactly one JSON object with these fields "
            f"(short scalar values only — a sentence or two, never file contents): {{{shape}}}"
        )
    else:
        lines.append('Your reply\'s LAST line must be exactly this JSON object: {"ok": true}')
    return "\n".join(lines)


# ---------------------------------------------------------------- transitions

def _require_cursor(run, path):
    if path not in _cursors(run):
        raise RunError(
            f"step {path!r} is not active (active: {', '.join(_cursors(run)) or 'none'})", code=4
        )


def complete_step(run, path, outputs=None, exit_code=None, stdout=None):
    _require_cursor(run, path)
    frame, node = run.node_at(path)
    entry = statemod.step_entry(run.state, path)
    if entry.get("pending_ask"):
        raise RunError(f"step {path!r} is waiting on a gate decision, not completion", code=4)
    kind = ntype(node)
    if kind == "script":
        return _complete_script(run, frame, node, path, entry, exit_code, stdout)
    if kind != "agent":
        raise RunError(f"complete is only valid for agent/script steps, not {kind}", code=4)

    outputs = outputs or {}
    missing = [f for f in node.get("outputs") or [] if f not in outputs]
    if missing:
        raise RunError(f"step {path!r}: missing output field(s): {', '.join(missing)}", code=4)
    bad_artifacts = [a for a in _artifact_list(run, frame, node) if not statemod.artifact_ok(a, run.root)]
    if bad_artifacts:
        raise RunError(
            f"step {path!r}: artifact missing or empty: {', '.join(bad_artifacts)} — "
            f"proof, not promises: re-run the step or call fail.", code=4,
        )
    entry["outputs"] = {k: v for k, v in outputs.items() if isinstance(v, (str, int, float, bool))}
    arts = _artifact_list(run, frame, node)
    if arts:
        entry["artifact"] = arts
    entry["status"] = "done"
    entry["attempts"] = 0
    _advance(run, frame, node, entry["outputs"])
    return entry


def _complete_script(run, frame, node, path, entry, exit_code, stdout):
    if exit_code is None:
        raise RunError("script completion requires --exit-code", code=4)
    outputs = {"exit_code": exit_code}
    text = (stdout or "").strip()
    if text:
        try:
            parsed = json.loads(text.splitlines()[-1])
            if isinstance(parsed, dict):
                outputs.update({
                    k: v for k, v in parsed.items() if isinstance(v, (str, int, float, bool))
                })
        except (ValueError, IndexError):
            pass
    entry["outputs"] = outputs
    if exit_code == 0:
        entry["status"] = "done"
        entry["attempts"] = 0
        _advance(run, frame, node, outputs)
    else:
        _register_failure(run, frame, node, path, entry,
                          reason=f"exit code {exit_code}: {text[:300]}")
    return entry


def fail_step(run, path, reason):
    _require_cursor(run, path)
    frame, node = run.node_at(path)
    entry = statemod.step_entry(run.state, path)
    entry.pop("pending_ask", None)
    _register_failure(run, frame, node, path, entry, reason)
    return entry


def _register_failure(run, frame, node, path, entry, reason):
    entry["attempts"] = entry.get("attempts", 0) + 1
    retries = node.get("retries", 1 if ntype(node) == "agent" else 0)
    entry["reason"] = reason
    if entry["attempts"] <= retries:
        entry["status"] = "pending"  # stays in cursors; next re-serves it
        return
    entry["status"] = "failed"
    _apply_on_fail(run, frame, node, reason)


def record_gate(run, path, option_id, input_text=None):
    _require_cursor(run, path)
    frame, node = run.node_at(path)
    entry = statemod.step_entry(run.state, path)
    ask = entry.get("pending_ask")
    run.state["gates"].append({
        "step": path, "option": option_id,
        **({"input": input_text} if input_text else {}),
        "at": statemod.now_iso(),
        **({"synthesized": ask["kind"]} if ask else {}),
    })
    if ask:
        return _record_synth_gate(run, frame, node, path, entry, ask, option_id)
    if ntype(node) != "gate":
        raise RunError(f"step {path!r} is not a gate", code=4)
    option = next((o for o in node["options"] if o["id"] == option_id), None)
    if option is None:
        valid = ", ".join(o["id"] for o in node["options"])
        raise RunError(f"gate {path!r}: unknown option {option_id!r} (valid: {valid})", code=4)
    if option.get("input") and not input_text:
        raise RunError(f"gate {path!r}: option {option_id!r} requires --input text", code=4)
    outputs = {"choice": option_id}
    if option.get("input"):
        outputs[option["input"]] = input_text
    entry["outputs"] = outputs
    entry["status"] = "done"
    _leave_to(run, frame, node, option["to"], outputs, via_gate=True)
    return entry


def _record_synth_gate(run, frame, node, path, entry, ask, option_id):
    kind = ask["kind"]
    if kind == "fail":
        if option_id == "retry":
            entry.pop("pending_ask", None)
            entry["attempts"] = 0
            if ntype(node) in ("subworkflow", "parallel"):
                # container nodes re-run from scratch: wipe nested state and re-enter
                _drop_cursor(run, path)
                for key in list(run.state["steps"]):
                    if key.startswith(path + "/") or key.startswith(path + "["):
                        del run.state["steps"][key]
                for key in list(run.state["frames"]):
                    if key == path or key.startswith(path + "/") or key.startswith(path + "["):
                        del run.state["frames"][key]
                entry.pop("branches", None)
                _enter_inner(run, frame, node)
            else:
                entry["status"] = "pending"
        elif option_id == "skip":
            entry.pop("pending_ask", None)
            entry["status"] = "skipped"
            target = _default_target(node)
            if target is None:
                raise RunError(f"cannot skip {path!r}: node has no default route", code=4)
            _leave_to(run, frame, node, target)
        elif option_id == "abort":
            _drop_cursor(run, path)
            _frame_abort(run, frame, reason=f"user aborted after failure at {path}")
        else:
            raise RunError(f"unknown option {option_id!r} (retry/skip/abort)", code=4)
    elif kind == "exhausted":
        if option_id == "continue":
            entry.pop("pending_ask", None)
            _drop_cursor(run, path)
            if entry.get("status") in ("done", "failed", "skipped"):
                _cascade_reset(run, frame, node["id"])
            _enter_inner(run, frame, node)
        elif option_id == "abort":
            _drop_cursor(run, path)
            _frame_abort(run, frame, reason=f"user aborted at visit cap of {path}")
        else:
            raise RunError(f"unknown option {option_id!r} (continue/abort)", code=4)
    else:  # branch_fail — node is the parallel node
        branch_id = ask["branch"]
        if option_id == "retry":
            entry.pop("pending_ask", None)
            _drop_cursor(run, path)
            branch = _find_branch(node, branch_id)
            prefix = path + f"[{branch_id}]/"
            for key in list(run.state["steps"]):
                if key.startswith(prefix):
                    del run.state["steps"][key]
            entry["branches"][branch_id] = {"status": "running"}
            bframe = Frame(
                "branch", prefix, frame.workflow, _nodes_by_id(branch["steps"]),
                branch["start"], frame.inputs, parent=frame, parent_node=node,
            )
            _enter(run, bframe, branch["start"])
        elif option_id == "skip":
            entry.pop("pending_ask", None)
            _drop_cursor(run, path)
            entry["branches"][branch_id]["status"] = "skipped"
            # re-run join accounting via a synthetic terminal check
            terminal = {
                b: r for b, r in entry["branches"].items()
                if r.get("status") in ("done", "failed", "skipped")
            }
            if len(terminal) == len(node.get("branches", [])):
                entry["status"] = "done"
                _advance(run, frame, node)
        elif option_id == "abort":
            _drop_cursor(run, path)
            _frame_abort(run, frame, reason=f"user aborted after branch {branch_id} failed")
        else:
            raise RunError(f"unknown option {option_id!r} (retry/skip/abort)", code=4)
    return entry


# ---------------------------------------------------------------- reset / rebase

def reset_steps(run, paths, cascade=False):
    for path in paths:
        frame, node = run.node_at(path)
        if cascade:
            # a manual cascade pulls execution back here: every downstream step is
            # reset (even pending ones sitting in the cursor frontier)
            for nid in _reachable(frame, node["id"]):
                if frame.path(nid) in run.state["steps"]:
                    _reset_step(run, frame, nid)
        else:
            _reset_step(run, frame, node["id"])
        _add_cursor(run, path)


def reset_all(run):
    data = run.state
    data["steps"] = {}
    data["frames"] = {}
    data["gates"] = []
    data["run"] = {"status": "running", "cursors": []}
    frame = run.main_frame()
    _enter(run, frame, frame.start)


def rebase(run):
    """Accept edited workflow files: re-hash everything recorded."""
    info = run.state["workflow"]
    info["sha256"] = statemod.sha256_file(os.path.join(run.root, info["file"]))
    for frame_info in run.state["frames"].values():
        full = os.path.join(run.root, frame_info["workflow"])
        if os.path.exists(full):
            frame_info["sha256"] = statemod.sha256_file(full)
