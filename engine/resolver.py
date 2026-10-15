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
import shlex

try:
    import condctl
    import memory as memorymod
    import state as statemod
    import validate as validatemod
    import validate_prd_questions as prdqmod
    import wf
except ImportError:  # imported as a package (tests)
    from . import (
        condctl,
        memory as memorymod,
        state as statemod,
        validate as validatemod,
        validate_prd_questions as prdqmod,
        wf,
    )


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

_PLACEHOLDER_RE = re.compile(r"\$\{([^{}]+)\}")
_MAX_SUBST_PASSES = 5


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
        self._memory_cache = None

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

        text = str(text)
        # Innermost-first regex + bounded loop resolves nested placeholders
        # (e.g. ${memory.knowledge.${inputs.stack}-review}) inside-out. The cap prevents a
        # resolved value that itself contains ${...} from looping forever.
        for _ in range(_MAX_SUBST_PASSES):
            new = _PLACEHOLDER_RE.sub(repl, text)
            if new == text:
                break
            text = new
        return text

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
            if parts[0] == "memory" and len(parts) == 3 and parts[1] == "knowledge":
                return self._memory_knowledge()[parts[2]]
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

    def _memory_knowledge(self):
        """The frozen memory snapshot for this run (loaded once, cached)."""
        if self._memory_cache is None:
            self._memory_cache = memorymod.load_snapshot(self.slug, self.root)
        return self._memory_cache

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

def coerce_input(declared, raw, name="input"):
    kind = (declared or {}).get("type", "string")
    try:
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
    except (ValueError, TypeError):
        raise RunError(f"input {name!r} is not a valid {kind}: {raw!r}", code=3)
    return raw


def init_run(slug, workflow_file, inputs, root=".", force=False):
    """Create (or no-op onto) the run ledger. Returns (state, created?)."""
    if not statemod.valid_slug(slug):
        raise RunError(
            f"invalid slug {slug!r}: use lowercase letters, digits, '.', '-', '_' "
            f"(a single path segment, no '/' or '..')", code=3,
        )
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
            resolved[name] = coerce_input(spec, resolved[name], name)
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
            resolved[name] = coerce_input(spec, default, name)

    data = statemod.new_state(slug, workflow_file, digest, resolved)
    # Freeze the memory knowledge snapshot for this run — read ONCE here, never re-read
    # live (keeps the run reproducible and immune to concurrent consolidation elsewhere).
    snap_path = memorymod.write_snapshot(slug, root, memorymod.read_knowledge(root))
    data["memory"] = {
        "snapshot": os.path.basename(snap_path),
        "sha256": statemod.sha256_file(snap_path),
    }
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
        elif target == "ask" or target == node_id:
            # `ask` (or an on_exhausted that points at this same node) synthesizes the
            # loop-limit gate. Routing on_exhausted back to self would recurse forever.
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
    metadata = {"node_type": kind}
    if kind == "agent":
        raw_skill = node.get("skill")
        metadata.update({
            "execution": node.get("execution", "worker"),
            "model": run.model_for(node, frame),
            "skill": run.resolve_text(raw_skill, frame) if raw_skill else None,
        })
    elif kind == "interview":
        raw_skill = node.get("skill")
        metadata.update({
            "execution": "lead",
            "skill": run.resolve_text(raw_skill, frame) if raw_skill else None,
        })
    statemod.mark_step_started(entry, **metadata)
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
        # missing_ok: a subworkflow input may reference a gate output that only exists on
        # some paths (e.g. `feedback` from a revise gate) — unset resolves to empty, same
        # as agent-node inputs (below), rather than aborting the run on first entry.
        child_inputs = {
            k: run.resolve_value(v, frame, missing_ok=True)
            for k, v in (node.get("inputs") or {}).items()
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


def _ancestors(frame, target):
    """Nodes from which `target` is forward-reachable (target itself excluded)."""
    return {
        nid for nid in frame.nodes
        if nid != target and target in _reachable(frame, nid)
    }


def _cascade_reset(run, frame, node_id):
    """Re-entry reset: the target plus every terminal-status step DOWNSTREAM of it.

    "Downstream" = forward-reachable from the target, minus the target's own ancestors.
    Excluding ancestors is what keeps a back-edge inside a loop (e.g. oq_record ->
    oq_serve) from cascading around the cycle and wiping the very upstream steps the
    target consumes (author_hld's HLD). Without it, re-entering a looped node silently
    resets its inputs; with it, each node still re-runs when the flow reaches it again
    (entering a done node triggers its own cascade), so nothing is left stale.
    """
    downstream = _reachable(frame, node_id) - _ancestors(frame, node_id)
    for nid in downstream:
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
        statemod.mark_step_finished(entry)
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
        statemod.mark_step_finished(entry)
        _advance(run, parent, node)
        return
    if len(terminal) == len(node.get("branches", [])):
        if join == "any" and not any(r.get("status") == "done" for r in terminal.values()):
            entry["status"] = "failed"
            entry["reason"] = "no branch completed"
            _apply_on_fail(run, parent, node, entry["reason"])
            return
        entry["status"] = "done"
        statemod.mark_step_finished(entry)
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

CLAIM_KEY = "dispatched_at"


def release_claims(state):
    """Forget which worker steps were handed out (a resumed session re-serves them)."""
    released = []
    for path, entry in (state.get("steps") or {}).items():
        if entry.pop(CLAIM_KEY, None) is not None:
            released.append(path)
    return released


def next_action(run, serial=False, claim=False, exclude_claimed=False):
    """Serve ONE action.

    Default (claim=False): pure and read-only — every runnable cursor is eligible, in the
    historical priority order (scripts, gates, interviews, lead agents, workers).

    claim=True: incremental dispatch. Worker steps already handed out (stamped with
    `dispatched_at`) are skipped, newly served worker steps are stamped, and ready workers
    are served BEFORE gates/interviews/lead work so one branch waiting on a human never
    holds back another branch's subagents. When only claimed workers remain, the action is
    `wait`. The caller must save the state. exclude_claimed=True gives the same view
    without stamping (read-only).
    """
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

    gates, scripts, interviews, lead_agents, worker_agents = [], [], [], [], []
    in_flight, pending_inputs = [], []
    for path in cursors:
        frame, node = run.node_at(path)
        entry = statemod.step_entry(run.state, path)
        if entry.get("pending_gate_input"):
            pending_inputs.append(_gate_input_action(run, frame, node, path, entry))
        elif entry.get("pending_ask"):
            gates.append(_synth_gate_action(run, path, node, entry))
        elif ntype(node) == "gate":
            gates.append(_gate_action(run, frame, node, path))
        elif ntype(node) == "script":
            scripts.append(_script_action(run, frame, node, path))
        elif ntype(node) == "agent":
            action = _agent_action(run, frame, node, path)
            if action["action"] == "run_lead":
                lead_agents.append(action)
            elif (claim or exclude_claimed) and entry.get(CLAIM_KEY):
                in_flight.append(path)
            else:
                worker_agents.append(action)
        elif ntype(node) == "interview":
            interviews.append(_interview_action(run, frame, node, path, entry))
        else:
            raise RunError(f"unexpected {ntype(node)} node in cursors: {path}")

    if scripts:
        return scripts[0]
    if pending_inputs:
        # the human just picked an option that needs text: finish that interaction first
        return pending_inputs[0]
    if claim or exclude_claimed:
        if worker_agents:
            served = worker_agents if not serial else worker_agents[:1]
            if claim:
                now = statemod.now_iso()
                for action in served:
                    statemod.step_entry(run.state, action["step"])[CLAIM_KEY] = now
            if len(served) > 1:
                return {"action": "run_agents", "agents": served}
            return served[0]
        if not (gates or interviews or lead_agents) and in_flight:
            return {
                "action": "wait",
                "in_flight": in_flight,
                "hint": "Nothing new to dispatch. Complete each in-flight step as its worker "
                        "finishes. If these workers are no longer running (e.g. a restarted "
                        "session), run `init` again to re-serve them.",
            }
    if gates:
        return gates[0]
    if interviews:
        return interviews[0]
    if lead_agents:
        return lead_agents[0]
    if len(worker_agents) > 1 and not serial:
        return {"action": "run_agents", "agents": worker_agents}
    if worker_agents:
        return worker_agents[0]
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


def _gate_input_action(run, frame, node, path, entry):
    pending = entry["pending_gate_input"]
    option = next((o for o in node["options"] if o["id"] == pending["option"]), None)
    if option is None or option.get("input") != pending.get("field"):
        raise RunError(f"gate {path!r}: pending input no longer matches the workflow", code=3)
    field = pending["field"]
    if field == "feedback":
        question = (
            f"You selected: {option['label']}\n\n"
            "What should Maestro change before regenerating? Give all suggestions together; "
            "for multiple LLDs, label each repository. Feedback is required and nothing will "
            "regenerate until it is recorded."
        )
    elif field == "answers_blob":
        question = (
            run.resolve_text(node["prompt"], frame, missing_ok=True).rstrip()
            + "\n\nProvide all answers together now. The question batch remains open until "
              "at least one non-blank line is recorded."
        )
    elif field == "refs":
        question = "Paste all reference links or local paths together now."
    elif field == "repos_text":
        question = "List the repositories to include, separated by commas."
    else:
        question = (
            f"You selected: {option['label']}\n\n"
            f"Provide the required {field.replace('_', ' ')}. Nothing will continue until "
            "this input is recorded."
        )
    return {
        "action": "ask_input",
        "step": path,
        "prompt": question,
        "option": option["id"],
        "field": field,
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
        "action": "run_lead" if node.get("execution") == "lead" else "run_agent",
        "step": path,
        "agent_type": run.agent_for(node, frame),
        "model": run.model_for(node, frame),
        "skill": skill,
        "isolate": isolate,
        "outputs": node.get("outputs") or [],
        "artifacts": artifacts,
        "prompt": render_agent_prompt(run, frame, node, resolved_inputs, artifacts, isolate, skill),
    }


def _interview_sections(run, frame, node):
    questions_artifact = node.get("questions_artifact")
    if questions_artifact:
        questions_rel = run.resolve_text(questions_artifact, frame)
        questions_full = (
            questions_rel if os.path.isabs(questions_rel)
            else os.path.join(run.root, questions_rel)
        )
        decisions_rel = run.resolve_text(node["artifact"], frame)
        decisions_full = (
            decisions_rel if os.path.isabs(decisions_rel)
            else os.path.join(run.root, decisions_rel)
        )
        errors, _warnings, document = prdqmod.validate(
            questions_full, decisions_path=decisions_full,
        )
        if errors:
            raise RunError(
                f"interview question queue {questions_rel!r} is invalid: "
                + " | ".join(errors[:5]),
                code=4,
            )
        questions = document.get("questions") if isinstance(document, dict) else []
        return [{
            "id": question["id"],
            "title": question["title"].strip(),
            "proposal": question.get("proposal", "").strip(),
            "prompt": question["question"].strip(),
            "why": question["why"].strip(),
            "must_resolve": list(question.get("must_resolve") or []),
            "kind": question.get("kind", "decision"),
            "alternatives": [
                {"label": alt["label"].strip(), "tradeoff": alt["tradeoff"].strip()}
                for alt in question.get("alternatives") or []
            ],
        } for question in questions]

    sections = []
    for section in node.get("sections") or []:
        sections.append({
            "id": section["id"],
            "title": run.resolve_text(section["title"], frame, missing_ok=True),
            "proposal": run.resolve_text(section.get("proposal", ""), frame, missing_ok=True).strip(),
            "prompt": run.resolve_text(section.get("prompt", ""), frame, missing_ok=True).strip(),
            "why": "",
            "must_resolve": [],
            "kind": "decision",
            "alternatives": [],
        })
    return sections


def _interview_action(run, frame, node, path, entry):
    sections = _interview_sections(run, frame, node)
    answers = (entry.get("interview") or {}).get("answers") or {}
    unresolved = [section for section in sections if section["id"] not in answers]
    if not unresolved:
        raise RunError(f"interview {path!r} has no unresolved section but is still active", code=4)
    context = run.resolve_text(node.get("context", ""), frame, missing_ok=True).strip()

    def payload(current):
        if current["prompt"]:
            question = current["prompt"]
        elif current["proposal"]:
            question = (
                f"For **{current['title']}**, Maestro currently understands:\n\n"
                f"{current['proposal']}\n\nIs this correct? Reply yes, or give the corrected answer."
            )
        else:
            question = (
                f"For **{current['title']}**, there is no grounded answer yet. "
                "What should the PRD say?"
            )
        return {
            "section": current["id"],
            "title": current["title"],
            "kind": current["kind"],
            "proposal": current["proposal"],
            "alternatives": current["alternatives"],
            "why": current["why"],
            "must_resolve": current["must_resolve"],
            "prompt": question,
        }

    skill = node.get("skill")
    if skill:
        skill = run.resolve_text(skill, frame)
    batch_size = node.get("batch_size", 1)
    if batch_size > 1:
        batch = [payload(section) for section in unresolved[:batch_size]]
        return {
            "action": "ask_interview_batch",
            "step": path,
            "skill": skill,
            "presentation": node.get("presentation", "chat"),
            "context": context,
            "questions": batch,
            "confirmed": answers,
            "progress": {"confirmed": len(answers), "total": len(sections)},
        }

    current = unresolved[0]
    current_payload = payload(current)
    return {
        "action": "ask_interview",
        "step": path,
        "skill": skill,
        "presentation": node.get("presentation", "chat"),
        "section": current_payload["section"],
        "title": current_payload["title"],
        "kind": current_payload["kind"],
        "proposal": current_payload["proposal"],
        "alternatives": current_payload["alternatives"],
        "why": current_payload["why"],
        "must_resolve": current_payload["must_resolve"],
        "context": context,
        "prompt": current_payload["prompt"],
        "confirmed": answers,
        "progress": {"confirmed": len(answers), "total": len(sections)},
    }


def _artifact_list(run, frame, node):
    raw = node.get("artifact")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    return [run.resolve_text(a, frame) for a in items]


def render_agent_prompt(run, frame, node, inputs, artifacts, isolate, skill=None):
    instruction = run.resolve_text(node["instruction"], frame, missing_ok=True)
    lines = [instruction.strip(), ""]
    if inputs:
        lines.append("Inputs:")
        for key, value in inputs.items():
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            lines.append(f"- {key}: {value}")
        lines.append("")
    if skill:
        # Reference the skill by NAME (the harness resolves installed skills from their
        # frontmatter name). The explicit candidates are the three supported repo-scoped
        # install locations, not pack-source paths: consumers do not have `skills/**`, and
        # workers must never compensate for a missing install with a machine-wide search.
        lines.append(
            f"Load and follow the `{skill}` skill to perform this task — read the first "
            f"non-empty SKILL.md below fully before acting; it owns the method and quality bar."
        )
        lines.extend([
            "Check ONLY these repository-scoped files:",
            f"- `.agents/skills/{skill}/SKILL.md`",
            f"- `.claude/skills/{skill}/SKILL.md`",
            f"- `.cursor/skills/{skill}/SKILL.md`",
            "Do not search parent directories, the home directory, Desktop, or the wider "
            "filesystem; never use a global `find` or `locate`, and do not use a native search "
            "fallback. If none exists, stop and report the missing installation instead of "
            "performing the task without the pinned skill."
        ])
    else:
        lines.append(
            "If an installed skill matches this task, load and follow it; otherwise proceed "
            "with your own best method."
        )
    if isolate == "worktree":
        slug = run.state["inputs"].get("slug", run.slug)
        # The branch MUST be unique per parallel step, or two worktrees try to check out
        # the same branch and git refuses. A node's own `branch` input (e.g. a stack-
        # specific `feature/${inputs.slug}-${inputs.stack}`) is unique by design, so prefer
        # it. Otherwise derive the name from the FULL step path — the bare node id collides
        # when the same subworkflow runs in more than one parallel branch (both would be
        # `.../implement`).
        branch = (inputs or {}).get("branch")
        if not branch:
            safe_path = frame.path(node["id"]).replace("[", "-").replace("]", "").replace("/", "-")
            branch = f"maestro/{slug}/{safe_path}"
        repo_path = (inputs or {}).get("repo_path")
        git_prefix = f"git -C {shlex.quote(str(repo_path))}" if repo_path else "git"
        location = (f" for the repository at `{repo_path}`" if repo_path else "")
        lines.append(
            f"ISOLATION IS MANDATORY. Before you edit ANY file, create and enter a git "
            f"worktree{location} on branch `{branch}`: run `{git_prefix} worktree add -b {branch} "
            f"<new-dir> HEAD` (or `{git_prefix} worktree add <new-dir> {branch}` if the branch "
            f"exists) and do all of your work from inside <new-dir>. Verify with `git rev-parse "
            f"--show-toplevel` that you are NOT in the main working tree before editing. If a "
            f"worktree cannot be created (e.g. the repo has no commits), STOP and report the "
            f"failure — do NOT fall back to editing the main working tree, because a parallel "
            f"step may be writing there. Commit your work on `{branch}` inside the worktree."
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


def complete_step(run, path, outputs=None, exit_code=None, stdout=None, telemetry=None):
    _require_cursor(run, path)
    frame, node = run.node_at(path)
    entry = statemod.step_entry(run.state, path)
    if entry.get("pending_ask"):
        raise RunError(f"step {path!r} is waiting on a gate decision, not completion", code=4)
    kind = ntype(node)
    if kind == "script":
        return _complete_script(run, frame, node, path, entry, exit_code, stdout, telemetry)
    if kind != "agent":
        raise RunError(f"complete is only valid for agent/script steps, not {kind}", code=4)

    outputs = outputs or {}
    declared = node.get("outputs") or []
    missing = [f for f in declared if f not in outputs]
    if missing:
        raise RunError(f"step {path!r}: missing output field(s): {', '.join(missing)}", code=4)
    nonscalar = [f for f in declared
                 if not isinstance(outputs[f], (str, int, float, bool))]
    if nonscalar:
        raise RunError(
            f"step {path!r}: output field(s) must be a scalar (string/number/bool), not an "
            f"array or object: {', '.join(nonscalar)}. Put structured data in an artifact "
            f"file and return its path instead.", code=4,
        )
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
    statemod.mark_step_finished(entry, telemetry)
    _advance(run, frame, node, entry["outputs"])
    return entry


def _complete_script(run, frame, node, path, entry, exit_code, stdout, telemetry=None):
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
        statemod.mark_step_finished(entry, telemetry)
        _advance(run, frame, node, outputs)
    else:
        _register_failure(run, frame, node, path, entry,
                          reason=f"exit code {exit_code}: {text[:300]}")
    return entry


def _write_interview_artifact(run, frame, node, path, sections, answers, turns, raised=()):
    rel = run.resolve_text(node["artifact"], frame)
    full = rel if os.path.isabs(rel) else os.path.join(run.root, rel)
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    now = statemod.now_iso()
    document = {}
    if os.path.exists(full):
        try:
            with open(full, encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict):
                document = existing
        except (OSError, ValueError):
            document = {}

    # Preserve artifacts from the original static-section interview format when a run is
    # upgraded in place. New rounds always use the cumulative decisions schema.
    decisions = document.get("decisions") if isinstance(document.get("decisions"), list) else []
    if not decisions:
        for old in document.get("sections") or []:
            if isinstance(old, dict) and old.get("id") and "answer" in old:
                decisions.append({
                    "id": old["id"],
                    "title": old.get("title", old["id"]),
                    "question": "",
                    "why": "",
                    "proposal": "",
                    "must_resolve": [],
                    "answer": old["answer"],
                    "source": "legacy-confirmed",
                    "confirmed_at": document.get("confirmed_at", now),
                })
    source_by_id = {turn.get("section"): turn for turn in turns if isinstance(turn, dict)}
    by_id = {
        item.get("id"): item for item in decisions
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for section in sections:
        turn = source_by_id.get(section["id"], {})
        decision = {
            "id": section["id"],
            "title": section["title"],
            "kind": section.get("kind", "decision"),
            "question": section["prompt"],
            "why": section["why"],
            "proposal": section["proposal"],
            "alternatives": section.get("alternatives", []),
            "must_resolve": section.get("must_resolve", []),
            "answer": answers[section["id"]],
            "source": turn.get("source", "user-answer"),
            "confirmed_at": turn.get("confirmed_at", now),
        }
        if turn.get("discussion"):
            decision["discussion"] = turn["discussion"]
        by_id[section["id"]] = decision
    # Points the human raised unprompted are their own statements: kept verbatim under fresh
    # ids so the next queue audit must account for them like any other confirmed input.
    raised_ids = []
    next_number = 1 + sum(1 for key in by_id if isinstance(key, str) and key.startswith("raised-"))
    for item in raised:
        while f"raised-{next_number}" in by_id:
            next_number += 1
        raised_id = f"raised-{next_number}"
        next_number += 1
        by_id[raised_id] = {
            "id": raised_id,
            "title": "Raised by the human",
            "kind": "decision",
            "question": "",
            "why": "",
            "proposal": "",
            "alternatives": [],
            "must_resolve": [],
            "answer": item["text"],
            "source": "user-raised",
            "confirmed_at": item.get("raised_at", now),
        }
        raised_ids.append(raised_id)
    rounds = document.get("rounds") if isinstance(document.get("rounds"), list) else []
    rounds.append({
        "confirmed_at": now,
        "question_ids": [item["id"] for item in sections] + raised_ids,
    })
    document = {
        "schema_version": 2,
        "slug": run.slug,
        "step": path,
        "context": run.resolve_text(node.get("context", ""), frame, missing_ok=True).strip(),
        "updated_at": now,
        "rounds": rounds,
        "decisions": list(by_id.values()),
    }
    tmp = f"{full}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, full)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return rel


def _finish_interview_if_complete(run, frame, node, path, entry, sections, interview):
    answers = interview["answers"]
    if len(answers) != len(sections):
        return
    context_path = _write_interview_artifact(
        run, frame, node, path, sections, answers, interview["turns"],
        raised=interview.get("raised") or [],
    )
    sources = [turn.get("source") for turn in interview["turns"]]
    raised_count = len(interview.get("raised") or [])
    entry["outputs"] = {
        "context_path": context_path,
        "confirmed_count": len(answers),
        "assumption_count": sources.count("assumption"),
        "deferred_count": sources.count("deferred"),
        "raised_count": raised_count,
        "summary": f"Recorded {len(answers)} decisions"
                   + (f" and {raised_count} raised points" if raised_count else ""),
    }
    entry["artifact"] = [context_path]
    entry["status"] = "done"
    statemod.mark_step_finished(entry, {
        "interview_turns": len(interview["turns"]),
    })
    _advance(run, frame, node, entry["outputs"])


RESPONSE_KINDS = ("accept", "answer", "option", "assume", "defer")


def _normalize_interview_response(path, section, response):
    """Map one human response to (answer, source, discussion) or raise; never mutates state.

    accept   — the served recommendation, confirmed as is.
    option   — the 1-based served alternative, recorded with its trade-off.
    answer   — the human's own words, verbatim.
    assume   — the human cannot settle it now and adopts the recommendation as a working
               assumption to verify later; downstream documents must flag it as such.
    defer    — the human cannot settle it now and parks it with a verbatim note; it is never a
               confirmed decision.
    discussion (optional) — the lead's short summary of what was explored before answering."""
    section_id = section["id"]
    if not isinstance(response, dict):
        raise RunError(f"interview {path!r}/{section_id}: response must be an object", code=4)
    unknown_keys = set(response) - set(RESPONSE_KINDS) - {"discussion"}
    if unknown_keys:
        raise RunError(
            f"interview {path!r}/{section_id}: unknown response fields {sorted(unknown_keys)}",
            code=4,
        )
    given = [
        kind for kind in RESPONSE_KINDS
        if kind in response and response[kind] not in (None, False)
    ]
    if len(given) != 1:
        raise RunError(
            f"interview {path!r}/{section_id}: provide exactly one of "
            f"accept=true, assume=true, option=<n>, answer or defer",
            code=4,
        )
    kind = given[0]
    value = response[kind]
    proposal = section["proposal"].strip()
    if kind in ("accept", "assume"):
        if value is not True:
            raise RunError(f"interview {path!r}/{section_id}: {kind} must be true", code=4)
        if not proposal:
            raise RunError(
                f"interview {path!r}/{section_id}: there is no proposed answer to {kind}",
                code=4,
            )
        answer, source = proposal, ("accepted-proposal" if kind == "accept" else "assumption")
    elif kind == "option":
        alternatives = section.get("alternatives") or []
        if isinstance(value, bool) or not isinstance(value, int) \
                or not 1 <= value <= len(alternatives):
            raise RunError(
                f"interview {path!r}/{section_id}: option must be 1..{len(alternatives)}",
                code=4,
            )
        chosen = alternatives[value - 1]
        answer, source = f"{chosen['label']} — {chosen['tradeoff']}", "chosen-alternative"
    else:
        if not isinstance(value, str) or not value.strip():
            raise RunError(f"interview {path!r}/{section_id}: {kind} cannot be blank", code=4)
        answer, source = value.strip(), ("user-answer" if kind == "answer" else "deferred")
    discussion = response.get("discussion")
    if discussion is not None and (not isinstance(discussion, str) or not discussion.strip()):
        raise RunError(
            f"interview {path!r}/{section_id}: discussion must be a non-empty string", code=4,
        )
    return answer, source, discussion.strip() if discussion else None


def _normalize_raised(path, raised):
    raised = list(raised or [])
    for text in raised:
        if not isinstance(text, str) or not text.strip():
            raise RunError(f"interview {path!r}: a raised point cannot be blank", code=4)
    return [text.strip() for text in raised]


def _record_interview_turns(interview, normalized, raised):
    now = statemod.now_iso()
    answers = interview.setdefault("answers", {})
    for section_id, value, source, discussion in normalized:
        answers[section_id] = value
        turn = {"section": section_id, "source": source, "confirmed_at": now}
        if discussion:
            turn["discussion"] = discussion
        interview["turns"].append(turn)
    if raised:
        interview.setdefault("raised", []).extend(
            {"text": text, "raised_at": now} for text in raised
        )


def record_interview(run, path, section_id, answer=None, accept=False, option=None,
                     assume=False, defer=None, discussion=None, raised=None):
    """Confirm exactly the currently served interview section and advance when complete."""
    _require_cursor(run, path)
    frame, node = run.node_at(path)
    if ntype(node) != "interview":
        raise RunError(f"step {path!r} is not an interview", code=4)
    entry = statemod.step_entry(run.state, path)
    sections = _interview_sections(run, frame, node)
    interview = entry.setdefault("interview", {"answers": {}, "turns": []})
    answers = interview.setdefault("answers", {})
    current = next((section for section in sections if section["id"] not in answers), None)
    if current is None:
        raise RunError(f"interview {path!r} is already complete", code=4)
    if section_id != current["id"]:
        raise RunError(
            f"interview {path!r}: expected section {current['id']!r}, got {section_id!r}", code=4,
        )
    response = {
        "accept": accept or None, "answer": answer, "option": option,
        "assume": assume or None, "defer": defer, "discussion": discussion,
    }
    response = {key: value for key, value in response.items() if value is not None}
    if "answer" in response and (not isinstance(answer, str) or not answer.strip()):
        raise RunError(f"interview {path!r}/{section_id}: answer cannot be blank", code=4)
    value, source, note = _normalize_interview_response(path, current, response)
    _record_interview_turns(interview, [(section_id, value, source, note)],
                            _normalize_raised(path, raised))
    _finish_interview_if_complete(run, frame, node, path, entry, sections, interview)
    return entry


def record_interview_batch(run, path, responses, raised=None):
    """Atomically confirm any clear answers from the currently served interview batch."""
    _require_cursor(run, path)
    frame, node = run.node_at(path)
    if ntype(node) != "interview":
        raise RunError(f"step {path!r} is not an interview", code=4)
    if not isinstance(responses, dict) or (not responses and not raised):
        raise RunError("batch interview responses must be a non-empty JSON object", code=4)

    entry = statemod.step_entry(run.state, path)
    sections = _interview_sections(run, frame, node)
    interview = entry.setdefault("interview", {"answers": {}, "turns": []})
    answers = interview.setdefault("answers", {})
    unresolved = [section for section in sections if section["id"] not in answers]
    batch_size = node.get("batch_size", 1)
    current_batch = unresolved[:batch_size]
    current_by_id = {section["id"]: section for section in current_batch}
    unknown = [section_id for section_id in responses if section_id not in current_by_id]
    if unknown:
        raise RunError(
            f"interview {path!r}: response id(s) are not in the current batch: {unknown}", code=4,
        )

    # Validate every response before mutating the ledger so a malformed final answer cannot
    # partially record earlier answers from the same human reply.
    normalized = []
    for section in current_batch:
        if section["id"] in responses:
            value, source, note = _normalize_interview_response(
                path, section, responses[section["id"]],
            )
            normalized.append((section["id"], value, source, note))
    _record_interview_turns(interview, normalized, _normalize_raised(path, raised))
    _finish_interview_if_complete(run, frame, node, path, entry, sections, interview)
    return entry


DISCUSSION_REPLY_WORDS = 120
DISCUSSION_AGENT = "discussant"


def interview_brief(run, path, section_id, mode="subagent"):
    """Read-only brief for discussing ONE served interview question outside the lead's context.

    `subagent` renders the prompt for an isolated, read-only discussion worker whose short
    replies the lead relays; `side` renders it for a separate session the human opens, which
    talks to them directly and records the outcome itself. Either way the evidence reading and
    reasoning never enter the lead's context. Mutates nothing."""
    if mode not in ("subagent", "side"):
        raise RunError(f"unknown discussion mode {mode!r}", code=4)
    _require_cursor(run, path)
    frame, node = run.node_at(path)
    if ntype(node) != "interview":
        raise RunError(f"step {path!r} is not an interview", code=4)
    entry = run.state.get("steps", {}).get(path) or {}
    answers = (entry.get("interview") or {}).get("answers") or {}
    sections = _interview_sections(run, frame, node)
    unresolved = [section for section in sections if section["id"] not in answers]
    served = unresolved[:node.get("batch_size", 1)]
    section = next((item for item in served if item["id"] == section_id), None)
    if section is None:
        raise RunError(
            f"interview {path!r}: {section_id!r} is not an unresolved question in the served "
            f"round (served: {', '.join(item['id'] for item in served) or 'none'})", code=4,
        )
    discuss = node.get("discuss") or {}
    skill = run.resolve_text(node["skill"], frame) if node.get("skill") else None
    inputs = {
        "confirmed_decisions": run.resolve_text(node["artifact"], frame),
        **{key: run.resolve_value(value, frame, missing_ok=True)
           for key, value in (discuss.get("inputs") or {}).items()},
    }
    context = run.resolve_text(node.get("context", ""), frame, missing_ok=True).strip()

    lines = [
        "Help a human think through ONE open question from a design interview. They are unsure "
        "of the answer or asked something back. Your job is to help them decide, not to decide "
        "for them.",
        "",
    ]
    if context:
        lines += ["Interview context:", context, ""]
    lines += [
        f"Question: {section['title']}",
        f"- Asked: {section['prompt']}",
        f"- Why it matters: {section['why'] or '(not stated)'}",
        f"- Recommendation: {section['proposal'] or '(none — no grounded recommendation yet)'}",
    ]
    for number, alternative in enumerate(section["alternatives"], 1):
        lines.append(f"- Alternative {number}: {alternative['label']} — {alternative['tradeoff']}")
    if section["must_resolve"]:
        lines.append("- A usable answer must make explicit: " + "; ".join(section["must_resolve"]))
    lines += ["", "Evidence you may read (read-only):"]
    for key, value in inputs.items():
        lines.append(f"- {key}: {json.dumps(value) if isinstance(value, (list, dict)) else value}")
    lines.append("")
    if skill:
        lines += [
            f"Load the `{skill}` skill from `.agents/skills/{skill}/SKILL.md`, "
            f"`.claude/skills/{skill}/SKILL.md`, or `.cursor/skills/{skill}/SKILL.md` and obey "
            "its read boundary and conversation standards. Do not search the wider filesystem.",
            "",
        ]
    lines += [
        "How to discuss:",
        "- Explain plainly what is being decided and what changes downstream with each option.",
        "- Give the reasoning behind the recommendation and say when an alternative would win; "
        "add an option the list missed if the evidence shows one.",
        "- Answer side questions from the evidence above and say what you checked. Never guess; "
        "if the evidence is silent or the fact belongs to someone else, say so and who could "
        "settle it.",
        "- Never edit files, the run state, or the decision artifact.",
        "",
    ]
    if mode == "subagent":
        lines += [
            "You run in an isolated context. The lead shows the human your reply verbatim and "
            "keeps only your final JSON line, so put everything the human needs in the reply.",
            f"- Keep each reply under {DISCUSSION_REPLY_WORDS} words and ask at most one question "
            "back.",
            "- End with ONE final line of compact JSON: "
            '{"status":"open|ready","candidate":"<the answer the human is converging on, '
            'in their terms, or empty>","summary":"<one sentence: what was explored>"}. '
            'Use "ready" only when the human has effectively settled.',
        ]
    else:
        responses = (
            '{"' + section["id"] + '":{"answer":"<their answer verbatim>",'
            '"discussion":"<one sentence: what was explored>"}}'
        )
        lines += [
            "You are talking to the human directly in a separate session, so the main run's "
            "context never sees this discussion. Keep turns short and let them steer.",
            "When they settle, confirm the exact outcome with them, then record it with ONE "
            'command (use option:<n>, accept:true, assume:true, or defer:"<note>" instead of '
            "answer when that is what they chose; add --raise '<point>' for anything new they "
            "raised):",
            "",
            f"python3 .maestro/engine/maestroctl.py interview-record-batch --slug {run.slug} "
            f"--step {path} --peek --responses '{responses}'",
            "",
            "If the command says the question is no longer open, it was already answered in the "
            "main session: tell the human and stop. Then tell them to return to the main session "
            "and say continue.",
        ]
    return {
        "action": "discuss",
        "mode": mode,
        "step": path,
        "section": section["id"],
        "skill": skill,
        "agent_type": discuss.get("agent") or DISCUSSION_AGENT,
        "model": run.model_for(discuss, frame),
        "question": {
            "title": section["title"], "prompt": section["prompt"], "why": section["why"],
            "proposal": section["proposal"], "alternatives": section["alternatives"],
        },
        "side_chat": {
            "claude_or_cursor": f"/maestro-discuss {run.slug} {path} {section['id']}",
            "codex": f"$maestro-discuss {run.slug} {path} {section['id']}",
        },
        "prompt": "\n".join(lines).rstrip() + "\n",
    }


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
        entry.pop(CLAIM_KEY, None)
        return
    entry["status"] = "failed"
    statemod.mark_step_finished(entry)
    _apply_on_fail(run, frame, node, reason)


def record_note(run, text, step=None):
    """Append an out-of-band user instruction to the ledger (no routing change).

    Gates and the requirement folder are the engine's structured inputs; this captures
    anything the human tells the lead agent IN CHAT outside a gate (a correction, a scope
    change) so `retrospect` can learn from it. Timestamped and tagged with the step(s) active
    when it was said (or an explicit `step`).
    """
    note = {
        "at": statemod.now_iso(),
        "text": text,
        "at_steps": [step] if step else list(run.state["run"].get("cursors") or []),
    }
    run.state.setdefault("notes", []).append(note)
    return note


def _append_gate_history(run, path, option_id, input_text=None, synthesized=None):
    run.state["gates"].append({
        "step": path, "option": option_id,
        **({"input": input_text} if input_text else {}),
        "at": statemod.now_iso(),
        **({"synthesized": synthesized} if synthesized else {}),
    })


def _finish_real_gate(run, frame, node, path, entry, option, input_text=None):
    outputs = {"choice": option["id"]}
    if option.get("input"):
        outputs[option["input"]] = input_text
    entry.pop("pending_gate_input", None)
    entry["outputs"] = outputs
    entry["status"] = "done"
    statemod.mark_step_finished(entry)
    _append_gate_history(run, path, option["id"], input_text=input_text)
    _leave_to(run, frame, node, option["to"], outputs, via_gate=True)
    return entry


def record_gate(run, path, option_id, input_text=None):
    _require_cursor(run, path)
    frame, node = run.node_at(path)
    entry = statemod.step_entry(run.state, path)
    ask = entry.get("pending_ask")
    if ask:
        _append_gate_history(run, path, option_id, synthesized=ask["kind"])
        return _record_synth_gate(run, frame, node, path, entry, ask, option_id)
    if ntype(node) != "gate":
        raise RunError(f"step {path!r} is not a gate", code=4)
    option = next((o for o in node["options"] if o["id"] == option_id), None)
    if option is None:
        valid = ", ".join(o["id"] for o in node["options"])
        raise RunError(f"gate {path!r}: unknown option {option_id!r} (valid: {valid})", code=4)
    if option.get("input") and not input_text:
        entry["pending_gate_input"] = {"option": option_id, "field": option["input"]}
        return entry
    return _finish_real_gate(run, frame, node, path, entry, option, input_text=input_text)


def record_gate_input(run, path, input_text):
    _require_cursor(run, path)
    frame, node = run.node_at(path)
    entry = statemod.step_entry(run.state, path)
    pending = entry.get("pending_gate_input")
    if not pending:
        raise RunError(f"gate {path!r} is not waiting for free text", code=4)
    if not input_text or not input_text.strip():
        raise RunError(f"gate {path!r}: {pending['field']} cannot be blank", code=4)
    option = next((o for o in node["options"] if o["id"] == pending["option"]), None)
    if option is None or option.get("input") != pending["field"]:
        raise RunError(f"gate {path!r}: pending input no longer matches the workflow", code=3)
    return _finish_real_gate(run, frame, node, path, entry, option, input_text=input_text)


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
                statemod.mark_step_started(entry)
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
        # Re-enter through _enter_inner so container nodes (parallel / subworkflow) rebuild
        # their nested state instead of sitting in the cursor frontier as a bare id — a raw
        # cursor on a container makes next_action raise "unexpected <type> node in cursors".
        _enter_inner(run, frame, node)


def reset_all(run):
    data = run.state
    data["steps"] = {}
    data["frames"] = {}
    data["gates"] = []
    data["run"] = {"status": "running", "cursors": []}
    frame = run.main_frame()
    _enter(run, frame, frame.start)


def rebase(run):
    """Accept edited workflow files: re-validate, then re-hash everything recorded."""
    info = run.state["workflow"]
    # Refuse to rebase onto a broken edit — otherwise the new hash is recorded and every
    # later command fails deep in the parser instead of here with a clear message.
    issues = validatemod.validate_file(info["file"], root=run.root)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        first = errors[0]
        raise RunError(
            f"cannot rebase: {info['file']} still has {len(errors)} validation error(s), "
            f"e.g. [{first.code}] {first.msg}. Fix the workflow, then rebase.",
            code=1,
        )
    info["sha256"] = statemod.sha256_file(os.path.join(run.root, info["file"]))
    for frame_info in run.state["frames"].values():
        full = os.path.join(run.root, frame_info["workflow"])
        if os.path.exists(full):
            frame_info["sha256"] = statemod.sha256_file(full)
