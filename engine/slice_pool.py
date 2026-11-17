#!/usr/bin/env python3
"""One repository's slice fan-out: the engine, not the implementer, splits a validated task plan.

  slice_pool.py init   --root . --slug S --repo R --tasks <tasks.json> --worktree W --branch B
  slice_pool.py claim  --root . --slug S --repo R --slot slot_1
  slice_pool.py record --root . --slug S --repo R --slot slot_1 --group G [--escalate true ...]
  slice_pool.py merge  --root . --slug S --repo R

`init` (impl.yaml's task-plan check) reads the validated tasks.json and decides `fanout`: true
when the plan has two or more slice groups and the engine created the feature worktree (clean,
on its branch); otherwise one implementer builds the whole repository, as before. It records the
groups in plan order and the feature branch's commit they all start from, under the run's
`.engine/slices/<repo>.json`. A new plan (the task step ran again) replaces the queue; the
previous plan's clean slice worktrees are removed and its branches deleted only when merged.

The fixed slots of impl-slices.yaml each `claim` one group at a time (`done` when none is left, or
once a slice escalated), get its own worktree and branch off that commit
(`<feature branch>-slice-<group>` at `.maestro/worktrees/<slug>/.slices/<repo>/<group>`), and
`record` the slice's result from the worktree itself: its HEAD, never the agent's word. A slot
that claimed a group and has not recorded it gets the same group again, so a resumed run never
loses one.

`merge` merges every slice commit into the feature branch in plan order (fast-forward, then merge
commits) in a scratch worktree, and moves the feature branch only when all of them merged, so a
conflict leaves the feature branch untouched. Writes are validated disjoint across groups, so a
conflict means the plan was wrong: it is reported as an escalation (with the files), never
resolved. Merging again is a no-op for slices already on the feature branch. After a clean merge
the slice worktrees are removed and their (merged) branches deleted.

Prints one JSON line; exits 1 with the reason on stderr when it cannot do its job.
MAESTRO_SIMULATION=1 fans out without git.
"""
import argparse
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_layout  # noqa: E402
import state as statemod  # noqa: E402
import worktrees  # noqa: E402

SCHEMA_VERSION = 1
SIMULATED_WORKTREE = "[simulated: no code was checked out]"
SIMULATED_COMMIT = "[simulated commit]"
SUMMARY_LIMIT = 300


class SliceError(RuntimeError):
    pass


def _simulated():
    return os.environ.get("MAESTRO_SIMULATION") == "1"


def _pool_path(root, slug, repo):
    return run_layout.path(slug, root, run_layout.slice_pool(repo))


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _load(root, slug, repo):
    try:
        doc = _read(_pool_path(root, slug, repo))
    except (OSError, ValueError) as exc:
        raise SliceError(f"slice queue for {repo} is unavailable: {exc}") from None
    if not isinstance(doc, dict):
        raise SliceError(f"slice queue for {repo} is not a JSON object")
    return doc


_git = worktrees._git


def _abs(root, path):
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))


def _flag(value):
    return str(value or "").strip().lower() == "true"


def _text(value):
    text = " ".join(str(value or "").split())
    return "" if text.lower() in ("", "none", "null") else text


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "slice"


def _ancestor(cwd, commit, of):
    rc, _ = _git(cwd, "merge-base", "--is-ancestor", commit, of)
    return rc == 0


def _groups(tasks_path):
    try:
        doc = _read(tasks_path)
        groups = [{"group_id": s["group_id"], "task_ids": list(s["task_ids"])}
                  for s in doc["slices"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SliceError(f"cannot read the slice groups from {tasks_path}: {exc}") from None
    if not groups:
        raise SliceError(f"{tasks_path} has no slice groups")
    return groups


def _feature_problem(worktree, branch):
    """Why the feature worktree cannot take slice merges, or None when it can."""
    if not worktree:
        return "no engine-created feature worktree"
    if not os.path.isdir(worktree):
        return f"the feature worktree {worktree} does not exist"
    rc, current = _git(worktree, "branch", "--show-current")
    if rc or (branch and current != branch):
        return f"the feature worktree is on {current or 'no branch'}, not {branch}"
    rc, dirty = _git(worktree, "status", "--porcelain")
    if rc or dirty:
        return "the feature worktree has uncommitted changes"
    return None


def _name_slices(root, slug, repo, branch, groups, generation):
    """Give each group a branch and worktree path that no earlier plan of this run used."""
    used = set()
    for group in groups:
        base = _safe(group["group_id"])
        name, n = base, 2
        while name in used:
            name, n = f"{base}-{n}", n + 1
        used.add(name)
        if generation > 1:
            name = f"{name}-r{generation}"
        group["branch"] = f"{branch}-slice-{name}"
        group["worktree"] = (SIMULATED_WORKTREE if _simulated() else os.path.join(
            root, worktrees.DEFAULT_DIR, slug, ".slices", repo, name))


def _remove_slice_worktree(feature, group):
    """Remove a slice worktree if clean and delete its branch only when it is merged (-d)."""
    kept = False
    path = group.get("worktree") or ""
    if os.path.isdir(path):
        rc, _ = _git(feature, "worktree", "remove", path)
        kept = bool(rc)
    if group.get("branch") and not kept:
        _git(feature, "branch", "-d", group["branch"])
    return not kept


def _drop_previous(previous):
    if not previous or _simulated():
        return
    feature = previous.get("feature_worktree") or ""
    if not os.path.isdir(feature):
        return
    for group in previous.get("groups") or []:
        _remove_slice_worktree(feature, group)
    _git(feature, "worktree", "prune")


def cmd_init(args):
    root = os.path.realpath(args.root)
    groups = _groups(_abs(root, args.tasks))
    feature = _abs(root, args.worktree) if args.worktree else ""
    fanout, reason, base = len(groups) >= 2, "", ""
    if len(groups) < 2:
        reason = "one slice group: one implementer builds the repository"
    elif not _simulated():
        problem = _feature_problem(feature, args.branch)
        if problem:
            fanout, reason = False, f"{problem}: one implementer builds the repository"
        else:
            _rc, base = _git(feature, "rev-parse", "HEAD")
    with statemod.locked(args.slug, root):
        path = _pool_path(root, args.slug, args.repo)
        try:
            previous = _read(path)
        except (OSError, ValueError):
            previous = None
        _drop_previous(previous)
        generation = int((previous or {}).get("generation") or 0) + 1
        _name_slices(root, args.slug, args.repo, args.branch, groups, generation)
        _write(path, {
            "schema_version": SCHEMA_VERSION, "repo": args.repo, "generation": generation,
            "fanout": fanout, "reason": reason, "feature_branch": args.branch,
            "feature_worktree": feature, "base_commit": base, "groups": groups,
            "remaining": [g["group_id"] for g in groups] if fanout else [],
            "assigned": {}, "results": {}, "merge": None,
        })
    summary = (f"{len(groups)} slice groups built in parallel" if fanout else
               f"{len(groups)} slice group(s), no fan-out ({reason})")
    print(json.dumps({"valid": True, "slice_count": len(groups), "fanout": fanout,
                      "groups_csv": ",".join(g["group_id"] for g in groups),
                      "fanout_summary": summary}))
    return 0


def _ensure_worktree(root, doc, group):
    """The group's own worktree on its own branch off the plan's base commit."""
    feature, path, branch = doc["feature_worktree"], group["worktree"], group["branch"]
    if os.path.isdir(path) and os.path.realpath(path) in worktrees._registered(feature):
        return
    worktrees._ignore_default_dir(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _git(feature, "worktree", "prune")
    rc, _ = _git(feature, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    if rc == 0:  # claimed before a resume: check its branch out again
        rc, out = _git(feature, "worktree", "add", "-q", path, branch)
    else:
        rc, out = _git(feature, "worktree", "add", "-q", "-b", branch, path, doc["base_commit"])
    if rc:
        raise SliceError(f"cannot create the worktree for slice {group['group_id']}: {out[-400:]}")


def cmd_claim(args):
    root = os.path.realpath(args.root)
    with statemod.locked(args.slug, root):
        doc = _load(root, args.slug, args.repo)
        assigned = doc.setdefault("assigned", {})
        results = doc.setdefault("results", {})
        group_id = assigned.get(args.slot)
        if group_id is None or group_id in results:
            assigned.pop(args.slot, None)
            stop = any(r.get("escalate") for r in results.values())
            if not doc.get("fanout") or stop or not doc.get("remaining"):
                _write(_pool_path(root, args.slug, args.repo), doc)
                print(json.dumps({"done": True, "group_id": "", "task_ids_csv": "",
                                  "task_count": 0, "branch": "", "worktree": ""}))
                return 0
            group_id = doc["remaining"].pop(0)
            assigned[args.slot] = group_id
        group = next(g for g in doc["groups"] if g["group_id"] == group_id)
        _write(_pool_path(root, args.slug, args.repo), doc)
        if not _simulated():
            _ensure_worktree(root, doc, group)
    print(json.dumps({"done": False, "group_id": group_id,
                      "task_ids_csv": ",".join(group["task_ids"]),
                      "task_count": len(group["task_ids"]), "branch": group["branch"],
                      "worktree": group["worktree"]}))
    return 0


def cmd_record(args):
    root = os.path.realpath(args.root)
    escalate = _flag(args.escalate)
    with statemod.locked(args.slug, root):
        doc = _load(root, args.slug, args.repo)
        group = next((g for g in doc.get("groups") or [] if g["group_id"] == args.group), None)
        if group is None:
            raise SliceError(f"slice {args.group!r} is not in {args.repo}'s plan")
        if _simulated():
            commit, empty = SIMULATED_COMMIT, False
        else:
            path, base = group["worktree"], doc["base_commit"]
            rc, current = _git(path, "branch", "--show-current")
            if rc or current != group["branch"]:
                raise SliceError(f"slice {args.group}: its worktree {path} is on "
                                 f"{current or 'no branch'}, not {group['branch']}")
            rc, dirty = _git(path, "status", "--porcelain")
            if (rc or dirty) and not escalate:
                raise SliceError(f"slice {args.group}: uncommitted changes in {path}; the slice "
                                 f"must commit its work on {group['branch']}")
            rc, commit = _git(path, "rev-parse", "HEAD")
            if rc or not _ancestor(path, base, commit):
                raise SliceError(f"slice {args.group}: {group['branch']} no longer starts from "
                                 f"the plan's base commit {base[:12]}")
            empty = commit == base
        doc.setdefault("results", {})[args.group] = {
            "commit": commit, "empty": empty, "escalate": escalate,
            "escalation": _text(args.escalation) if escalate else "",
            "tests_passed": _flag(args.tests_passed),
            "summary": _text(args.summary)[:SUMMARY_LIMIT],
        }
        if doc.setdefault("assigned", {}).get(args.slot) == args.group:
            doc["assigned"].pop(args.slot)
        _write(_pool_path(root, args.slug, args.repo), doc)
    print(json.dumps({"recorded": args.group, "commit": commit, "empty": empty,
                      "escalate": escalate}))
    return 0


def _summary(doc):
    parts = []
    for group in doc["groups"]:
        result = doc["results"].get(group["group_id"]) or {}
        text = f"{group['group_id']}: {result.get('summary') or 'no summary'}"
        if result.get("empty"):
            text += " (no commit)"
        elif not result.get("tests_passed"):
            text += " (its tests were not reported passing)"
        parts.append(text)
    return "; ".join(parts)


def _merge_result(doc, **fields):
    out = {"merged": False, "escalate": False, "escalation": "None", "conflict": False,
           "branch": doc.get("feature_branch") or "", "worktree": doc.get("feature_worktree") or "",
           "commit": "", "slice_count": len(doc.get("groups") or []), "summary": ""}
    out.update(fields)
    return out


def _merge_all(doc, feature):
    """Merge every slice in plan order in a scratch worktree, then fast-forward the feature
    branch to it. Returns (commit, None) or (None, conflict report)."""
    rc, head = _git(feature, "rev-parse", "HEAD")
    if rc:
        raise SliceError(f"cannot read the feature branch's HEAD in {feature}")
    pending = [g for g in doc["groups"] if not doc["results"][g["group_id"]]["empty"]
               and not _ancestor(feature, doc["results"][g["group_id"]]["commit"], head)]
    if not pending:
        return head, None
    scratch = os.path.join(os.path.dirname(pending[0]["worktree"]), ".merge")
    _git(feature, "worktree", "remove", "--force", scratch)  # left by an interrupted merge
    shutil.rmtree(scratch, ignore_errors=True)
    _git(feature, "worktree", "prune")
    rc, out = _git(feature, "worktree", "add", "-q", "--detach", scratch, head)
    if rc:
        raise SliceError(f"cannot create the merge worktree: {out[-400:]}")
    try:
        for group in pending:
            result = doc["results"][group["group_id"]]
            message = (f"Merge slice {group['group_id']} ({len(group['task_ids'])} tasks) "
                       f"into {doc['feature_branch']}")
            rc, out = _git(scratch, "merge", "--no-edit", "-m", message, result["commit"])
            if rc:
                _rc, files = _git(scratch, "diff", "--name-only", "--diff-filter=U")
                _git(scratch, "merge", "--abort")
                if not files:
                    raise SliceError(f"merging slice {group['group_id']} failed: {out[-400:]}")
                merged = [g["group_id"] for g in pending[:pending.index(group)]]
                return None, {"group": group["group_id"], "files": files.splitlines(),
                              "after": merged}
        rc, merged_head = _git(scratch, "rev-parse", "HEAD")
        rc, out = _git(feature, "merge", "--ff-only", "-q", merged_head)
        if rc:
            raise SliceError(f"cannot move {doc['feature_branch']} to the merged commit: "
                             f"{out[-400:]}")
        return merged_head, None
    finally:
        _git(feature, "worktree", "remove", "--force", scratch)


def cmd_merge(args):
    root = os.path.realpath(args.root)
    with statemod.locked(args.slug, root):
        doc = _load(root, args.slug, args.repo)
    if not doc.get("fanout"):
        raise SliceError(f"{args.repo}'s plan was not fanned out ({doc.get('reason')})")
    results = doc.get("results") or {}
    escalated = [f"slice {gid}: {r.get('escalation') or 'stopped'}"
                 for gid, r in results.items() if r.get("escalate")]
    missing = [g["group_id"] for g in doc["groups"] if g["group_id"] not in results]
    if escalated or missing:
        text = "; ".join(escalated)
        if missing:
            text += ("; " if text else "") + f"not built: {', '.join(missing)}"
        print(json.dumps(_merge_result(doc, escalate=True, escalation=text,
                                       summary=_summary(doc) if results else "")))
        return 0
    feature, conflict = doc["feature_worktree"], None
    if _simulated():
        commit = SIMULATED_COMMIT
    else:
        problem = _feature_problem(feature, doc["feature_branch"])
        if problem:
            raise SliceError(f"cannot merge the slices: {problem}")
        commit, conflict = _merge_all(doc, feature)
    with statemod.locked(args.slug, root):
        doc = _load(root, args.slug, args.repo)
        if conflict:
            doc["merge"] = {"status": "conflict", **conflict, "at": statemod.now_iso()}
        else:
            doc["merge"] = {"status": "merged", "commit": commit, "at": statemod.now_iso()}
            if not _simulated():
                kept = [g["group_id"] for g in doc["groups"]
                        if not _remove_slice_worktree(feature, g)]
                doc["merge"]["kept_worktrees"] = kept
        _write(_pool_path(root, args.slug, args.repo), doc)
    if _simulated():
        doc["feature_worktree"] = doc.get("feature_worktree") or SIMULATED_WORKTREE
    if conflict:
        after = (f" after merging {', '.join(conflict['after'])}" if conflict["after"] else "")
        text = (f"merging slice {conflict['group']} into {doc['feature_branch']}{after} conflicts "
                f"in {', '.join(conflict['files'])}: the plan put writes to the same files in "
                f"different slice groups. The feature branch is unchanged and every slice branch "
                f"is kept; re-plan with those files in one group")
        print(json.dumps(_merge_result(doc, escalate=True, conflict=True, escalation=text,
                                       summary=_summary(doc))))
        return 0
    print(json.dumps(_merge_result(
        doc, merged=True, commit=commit,
        summary=f"Merged {len(doc['groups'])} slices into {doc['feature_branch']}: "
                + _summary(doc))))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    commands = {}
    for name, fn in (("init", cmd_init), ("claim", cmd_claim), ("record", cmd_record),
                     ("merge", cmd_merge)):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".")
        p.add_argument("--slug", required=True)
        p.add_argument("--repo", required=True)
        p.set_defaults(fn=fn)
        commands[name] = p
    commands["init"].add_argument("--tasks", required=True)
    commands["init"].add_argument("--worktree", default="")
    commands["init"].add_argument("--branch", required=True)
    commands["claim"].add_argument("--slot", required=True)
    commands["record"].add_argument("--slot", required=True)
    commands["record"].add_argument("--group", required=True)
    commands["record"].add_argument("--escalate", default="false")
    commands["record"].add_argument("--escalation", default="")
    commands["record"].add_argument("--tests-passed", default="")
    commands["record"].add_argument("--summary", default="")
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except SliceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
