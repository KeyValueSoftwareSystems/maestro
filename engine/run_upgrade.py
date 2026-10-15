#!/usr/bin/env python3
"""One-time upgrade of legacy Maestro runs into the current workflow layout.

The command never translates old step identifiers.  Compatible ledgers are backed up, rebased,
re-nested where a workflow moved inline steps into a stage child (identifiers unchanged, see
relayout_stages), and stamped.  Truly legacy ledgers are backed up and rebuilt from validated
artifacts; the current workflow then asks the human to approve the imported PRD/HLD baseline,
creates independent LLD children, and requires each imported LLD to pass today's validator and
approval gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import lld_repo_pool  # noqa: E402
import resolver  # noqa: E402
import state as statemod  # noqa: E402
import validate as validatemod  # noqa: E402
import validate_hld  # noqa: E402
import validate_lld  # noqa: E402
import validate_prd  # noqa: E402
import wf  # noqa: E402


SCHEMA_VERSION = 1
LEGACY_STEP_IDS = {
    "author_llds", "brainstorm_draft", "brainstorm_fold",
    "rq_ask", "rq_fold", "rq_prepare", "rq_validate", "design_review",
}


_HEAD_RE = re.compile(r"[/\[]")


def _relayout_frame(run, prefix, created):
    """Re-key the legacy inline steps of the frame at `prefix` under the stage that owns them."""
    state = run.state
    try:
        frame = run.frame_for(prefix + "_")
    except resolver.RunError:
        return
    stages = [node for node in frame.nodes.values() if resolver.ntype(node) == "subworkflow"]
    stage_of = {}
    for node in stages:
        for child_node in run.load_workflow(node["workflow"])["nodes"]:
            stage_of.setdefault(child_node["id"], node["id"])

    def owner(head):
        stage = stage_of.get(head)
        if stage is None or head not in frame.nodes:
            return stage
        # A current node id is legacy only where the old inline step shared its stage's name
        # (`contract` was an agent and is now the contract stage) and was never that stage.
        entry = state["steps"].get(prefix + head) or {}
        if stage != head or prefix + head in state["frames"] or entry.get("node_type") == "subworkflow":
            return None
        return stage

    def remap(path):
        if not path or not path.startswith(prefix):
            return path
        rest = path[len(prefix):]
        stage = owner(_HEAD_RE.split(rest, 1)[0])
        return f"{prefix}{stage}/{rest}" if stage else path

    moved = {path for path in state["steps"] if remap(path) != path}
    if not moved:
        return
    state["steps"] = {remap(path): entry for path, entry in state["steps"].items()}
    state["frames"] = {remap(path): info for path, info in state["frames"].items()}
    state["run"]["cursors"] = [remap(path) for path in state["run"].get("cursors") or []]
    for gate in state.get("gates") or []:
        gate["step"] = remap(gate.get("step"))
    for note in state.get("notes") or []:
        if isinstance(note.get("at_steps"), list):
            note["at_steps"] = [remap(path) for path in note["at_steps"]]

    cursors = state["run"]["cursors"]
    for node in stages:
        path = prefix + node["id"]
        inside = [key for key in state["steps"] if key.startswith(path + "/")]
        if not inside or path in state["frames"]:
            continue
        rel = node["workflow"]
        sha = statemod.sha256_file(os.path.join(run.root, rel))
        state["frames"][path] = {
            "workflow": rel, "sha256": sha,
            "inputs": resolver.subworkflow_inputs(run, frame, node, run.load_workflow(rel, sha)),
        }
        if any(cursor.startswith(path + "/") for cursor in cursors):
            status = "running"
        elif any(state["steps"][key].get("status") == "failed" for key in inside):
            status = "failed"
        else:
            status = "done"
        entry = {"status": status, "attempts": 0, "visits": 1, "outputs": {},
                 "node_type": "subworkflow"}
        state["steps"][path] = entry
        if status == "done":
            child = run._sub_frame(frame, node)
            entry["outputs"] = {
                key: run.resolve_value(value, child, missing_ok=True)
                for key, value in (child.workflow.get("outputs") or {}).items()
            }
        created.append(path)


def relayout_stages(run):
    """Run format 2 -> 3: inline steps moved into small stage child workflows.

    Every ledger path a frame owned inline (`design/author_hld`, `qa/run_tests`,
    `implement[slot_1]/claim`) is re-keyed under the stage subworkflow node whose child now
    declares it (`design/hld/author_hld`, `delivery/qa/run_tests`) — steps, frames, cursors, gate
    history and note anchors alike. Each touched stage then gets the subworkflow entry and frame
    record the resolver would have written on entry: running when a cursor is inside it, otherwise
    done with its child outputs resolved. Parents are processed before children, so a stage
    created here is relaid out in turn. The exact cursor survives. Returns the stage paths created;
    a ledger already in the stage layout is left alone.
    """
    state = run.state
    created, seen = [], set()
    while True:
        prefixes = [""] + [path + "/" for path in sorted(
            state["frames"], key=lambda path: (path.count("/"), path))]
        todo = [prefix for prefix in prefixes if prefix not in seen]
        if not todo:
            return created
        seen.add(todo[0])
        _relayout_frame(run, todo[0], created)


def _run_dir(slug, root):
    return statemod.feature_dir(slug, root)


def _manifest_path(slug, root):
    return os.path.join(_run_dir(slug, root), "run-upgrade.json")


def _atomic_json(path, document):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=os.path.dirname(path), delete=False) as fh:
        tmp = fh.name
        json.dump(document, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _raw_state(slug, root):
    path = statemod.state_path(slug, root)
    if not os.path.isfile(path):
        return None, None
    try:
        return wf.load_file(path), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def _selected_repos(slug, root):
    path = os.path.join(_run_dir(slug, root), "lld-repos.json")
    try:
        doc = _load_json(path)
    except (OSError, ValueError):
        doc = {}
    selected = doc.get("selected") if isinstance(doc, dict) else []
    return [item for item in (selected or []) if isinstance(item, str) and item.strip()]


def _legacy_llds(slug, root, selected):
    directory = os.path.join(_run_dir(slug, root), "lld")
    result = {}
    for repo in selected:
        path = os.path.join(directory, f"{repo}.md")
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            errors, warnings = validate_lld.validate(path, parent_slug=slug, repo=repo)
            result[repo] = {
                "path": os.path.relpath(path, root),
                "sha256": statemod.sha256_file(path),
                "valid": not errors,
                "issues": (errors + warnings)[:8],
            }
    return result


def _artifact_validation(slug, root, selected):
    run_dir = _run_dir(slug, root)
    prd = os.path.join(run_dir, "requirement", "prd.md")
    hld = os.path.join(run_dir, "hld.md")
    open_questions = os.path.join(run_dir, "open-questions.json")
    prd_errors, prd_warnings = validate_prd.validate(prd) if os.path.isfile(prd) else (
        ["PRD is missing"], [],
    )
    hld_errors, hld_warnings = validate_hld.validate(
        hld, open_questions_path=open_questions if os.path.isfile(open_questions) else None,
    ) if os.path.isfile(hld) else (["HLD is missing"], [])
    return {
        "prd": {
            "path": os.path.relpath(prd, root), "valid": not prd_errors,
            "issues": (prd_errors + prd_warnings)[:8],
            **({"sha256": statemod.sha256_file(prd)} if os.path.isfile(prd) else {}),
        },
        "hld": {
            "path": os.path.relpath(hld, root), "valid": not hld_errors,
            "issues": (hld_errors + hld_warnings)[:8],
            **({"sha256": statemod.sha256_file(hld)} if os.path.isfile(hld) else {}),
        },
        "llds": _legacy_llds(slug, root, selected),
    }


def _is_legacy(state, slug, root):
    if state is None:
        return True
    basenames = {path.rsplit("/", 1)[-1] for path in (state.get("steps") or {})}
    paths = set((state.get("steps") or {}))
    if basenames & LEGACY_STEP_IDS or "design/lld_approval" in paths:
        return True
    queue_path = os.path.join(_run_dir(slug, root), "lld-repos.json")
    try:
        queue = _load_json(queue_path)
    except (OSError, ValueError):
        queue = {}
    return bool(
        queue.get("selected") and not queue.get("workstreams")
        and os.path.isdir(os.path.join(_run_dir(slug, root), "lld"))
    )


def inspect(slug, root, workflow):
    state, state_error = _raw_state(slug, root)
    if state is None and state_error is None:
        return {"needed": False, "reason": "run does not exist", "slug": slug}
    if state and state.get("run_format") == statemod.RUN_FORMAT_VERSION:
        return {
            "needed": False, "reason": "run already uses the current format", "slug": slug,
            "run_format": statemod.RUN_FORMAT_VERSION,
        }
    mode = "legacy-rebuild" if _is_legacy(state, slug, root) else "compatible-rebase"
    selected = _selected_repos(slug, root)
    validations = _artifact_validation(slug, root, selected) if mode == "legacy-rebuild" else {}
    feature = ((state or {}).get("inputs") or {}).get("feature") or slug
    return {
        "needed": True,
        "one_time": True,
        "slug": slug,
        "mode": mode,
        "state_readable": state is not None,
        "state_error": state_error,
        "source_workflow": ((state or {}).get("workflow") or {}).get("file"),
        "target_workflow": workflow,
        "feature": feature,
        "selected_repos": selected,
        "validations": validations,
        "baseline_valid": (
            validations["prd"]["valid"] and validations["hld"]["valid"]
            if validations else True
        ),
    }


def _backup_state(slug, root):
    source = statemod.state_path(slug, root)
    with open(source, "rb") as fh:
        content = fh.read()
    digest = hashlib.sha256(content).hexdigest()
    target = os.path.join(_run_dir(slug, root), f"state.pre-upgrade-{digest[:12]}.yaml")
    if not os.path.exists(target):
        shutil.copy2(source, target)
    return target, digest


def _backup_artifacts(slug, root):
    run_dir = _run_dir(slug, root)
    backup_dir = os.path.join(run_dir, "legacy-artifacts")
    sources = list(_artifact_validation(slug, root, _selected_repos(slug, root))["llds"].values())
    paths = [item["path"] for item in sources]
    paths.extend([
        os.path.relpath(os.path.join(run_dir, "requirement", "prd.md"), root),
        os.path.relpath(os.path.join(run_dir, "hld.md"), root),
        os.path.relpath(os.path.join(run_dir, "open-questions.json"), root),
        os.path.relpath(os.path.join(run_dir, "lld-repos.json"), root),
    ])
    copied = []
    for relative in paths:
        source = relative if os.path.isabs(relative) else os.path.join(root, relative)
        if not os.path.isfile(source):
            continue
        inside_run = os.path.relpath(source, run_dir)
        target = os.path.join(backup_dir, inside_run)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not os.path.exists(target):
            shutil.copy2(source, target)
        copied.append(os.path.relpath(target, root))
    return copied


def apply(slug, root, workflow):
    plan = inspect(slug, root, workflow)
    if not plan["needed"]:
        plan["applied"] = False
        return plan
    issues = validatemod.validate_file(workflow, root=root)
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        raise ValueError(f"target workflow has {len(errors)} validation error(s): {errors[0]}")
    with statemod.locked(slug, root):
        # Re-check while holding the run lock so concurrent invocations cannot upgrade twice.
        current = inspect(slug, root, workflow)
        if not current["needed"]:
            current["applied"] = False
            return current
        backup, source_sha = _backup_state(slug, root)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            **current,
            "source_state_backup": os.path.relpath(backup, root),
            "source_state_sha256": source_sha,
            "legacy_artifacts": (
                _backup_artifacts(slug, root) if current["mode"] == "legacy-rebuild" else []
            ),
            "status": "applied",
            "applied_at": statemod.now_iso(),
        }
        manifest_path = _manifest_path(slug, root)
        _atomic_json(manifest_path, manifest)
        if current["mode"] == "compatible-rebase":
            state = statemod.load(slug, root)
            if state is None:
                raise ValueError("compatible upgrade cannot load the existing state")
            run = resolver.Run(slug, root, state_data=state)
            resolver.rebase(run)
            relayout_stages(run)
            run.state["run_format"] = statemod.RUN_FORMAT_VERSION
            run.state["upgrade"] = {
                "manifest": os.path.relpath(manifest_path, root),
                "source_state_backup": os.path.relpath(backup, root),
            }
            statemod.save(slug, run.state, root)
        else:
            inputs = {
                "feature": current["feature"],
                "upgrade_manifest": os.path.relpath(manifest_path, root),
            }
            data, _created = resolver.init_run(slug, workflow, inputs, root, force=True)
            data["upgrade"] = {
                "manifest": os.path.relpath(manifest_path, root),
                "source_state_backup": os.path.relpath(backup, root),
            }
            statemod.save(slug, data, root)
    return {
        "needed": False,
        "applied": True,
        "one_time": True,
        "slug": slug,
        "mode": plan["mode"],
        "manifest_path": os.path.relpath(_manifest_path(slug, root), root),
        "backup_path": os.path.relpath(backup, root),
        "next": "resume the run normally",
    }


def validate_baseline(manifest_path, root):
    full = manifest_path if os.path.isabs(manifest_path) else os.path.join(root, manifest_path)
    manifest = _load_json(full)
    if manifest.get("status") != "applied":
        raise ValueError("legacy baseline can be validated only before activation or skip")
    selected = manifest.get("selected_repos") or []
    validations = _artifact_validation(manifest["slug"], root, selected)
    valid = validations["prd"]["valid"] and validations["hld"]["valid"]
    manifest["validations"] = validations
    manifest["baseline_valid"] = valid
    manifest["validated_at"] = statemod.now_iso()
    _atomic_json(full, manifest)
    issues = validations["prd"]["issues"] + validations["hld"]["issues"]
    return {
        "valid": valid,
        "issues_summary": " | ".join(issues[:8]) if issues else "Imported PRD and HLD pass current validators",
        "summary": resume(manifest_path, root)["summary"],
    }


def resume(manifest_path, root):
    if not manifest_path:
        return {"state": "normal", "available": False, "baseline_valid": False, "summary": "normal run"}
    full = manifest_path if os.path.isabs(manifest_path) else os.path.join(root, manifest_path)
    try:
        manifest = _load_json(full)
    except (OSError, ValueError):
        return {"state": "normal", "available": False, "baseline_valid": False, "summary": "upgrade manifest missing"}
    available = manifest.get("status") == "applied" and manifest.get("mode") == "legacy-rebuild"
    validations = manifest.get("validations") or {}
    selected = manifest.get("selected_repos") or []
    llds = validations.get("llds") or {}
    summary = (
        f"Imported PRD: {'valid' if (validations.get('prd') or {}).get('valid') else 'needs repair'}; "
        f"HLD: {'valid' if (validations.get('hld') or {}).get('valid') else 'needs repair'}; "
        f"scope: {', '.join(selected) or 'not selected'}; "
        f"existing LLD drafts: {', '.join(sorted(llds)) or 'none'}."
    )
    return {
        "state": "ready" if available and manifest.get("baseline_valid") else (
            "invalid" if available else "normal"
        ),
        "available": available,
        "baseline_valid": bool(manifest.get("baseline_valid")),
        "summary": summary,
        "selected_csv": ",".join(selected),
        "existing_llds_csv": ",".join(sorted(llds)),
    }


def _set_manifest_status(path, root, status):
    full = path if os.path.isabs(path) else os.path.join(root, path)
    manifest = _load_json(full)
    if manifest.get("status") not in ("applied", status):
        raise ValueError(f"upgrade manifest cannot move from {manifest.get('status')} to {status}")
    manifest["status"] = status
    manifest[f"{status}_at"] = statemod.now_iso()
    _atomic_json(full, manifest)
    return manifest


def skip(manifest_path, root):
    manifest = _set_manifest_status(manifest_path, root, "skipped")
    return {"skipped": True, "slug": manifest["slug"]}


def activate(manifest_path, root, child_workflow):
    full = manifest_path if os.path.isabs(manifest_path) else os.path.join(root, manifest_path)
    manifest = _load_json(full)
    if manifest.get("status") == "activated":
        workstreams = manifest.get("workstreams") or []
        return {
            "activated": True,
            "has_workstreams": bool(workstreams),
            "count": len(workstreams),
            "selected_csv": ",".join(item.get("repo", "") for item in workstreams),
            "hld_summary": "Validated imported HLD baseline",
            "workstreams_md": manifest.get("workstreams_md") or "",
        }
    if manifest.get("status") != "applied" or not manifest.get("baseline_valid"):
        raise ValueError("only a valid, human-approved imported baseline can be activated")
    parent = manifest["slug"]
    selected = manifest.get("selected_repos") or []
    if not selected:
        manifest["status"] = "skipped"
        manifest["skipped_at"] = statemod.now_iso()
        _atomic_json(full, manifest)
        return {
            "activated": False, "has_workstreams": False, "count": 0,
            "selected_csv": "", "hld_summary": "Validated imported HLD baseline",
            "workstreams_md": "No legacy LLD scope found.",
        }
    repo_paths = {
        name: os.path.relpath(path, root) for name, path in codebase_scan.discover_repos(root)
    }
    missing = [repo for repo in selected if repo not in repo_paths]
    if missing:
        raise ValueError(f"legacy LLD repositories are no longer discoverable: {missing}")
    parent_hld = os.path.join(_run_dir(parent, root), "hld.md")
    hld_sha = statemod.sha256_file(parent_hld)
    workstreams = []
    legacy_llds = (manifest.get("validations") or {}).get("llds") or {}
    for repo in selected:
        child_slug = lld_repo_pool._child_slug(parent, repo)
        imported = legacy_llds.get(repo, {}).get("path", "")
        child_lld = os.path.join(_run_dir(child_slug, root), "lld.md")
        child_inputs = {
            "parent_slug": parent,
            "repo": repo,
            "repo_path": repo_paths[repo],
            "feature": manifest.get("feature") or parent,
            "imported_lld": os.path.relpath(child_lld, root) if imported else "",
        }
        with statemod.locked(child_slug, root):
            existing = statemod.load(child_slug, root)
            if existing is not None:
                inputs = existing.get("inputs") or {}
                if inputs.get("parent_slug") != parent or inputs.get("repo") != repo:
                    raise ValueError(f"child slug {child_slug!r} belongs to another workstream")
                if imported and inputs.get("imported_lld") != child_inputs["imported_lld"]:
                    raise ValueError(
                        f"existing child {child_slug!r} is not the expected imported LLD draft"
                    )
            if imported:
                source = imported if os.path.isabs(imported) else os.path.join(root, imported)
                if os.path.isfile(child_lld):
                    if statemod.sha256_file(source) != statemod.sha256_file(child_lld):
                        raise ValueError(
                            f"refusing to overwrite changed imported LLD in {child_slug!r}"
                        )
                else:
                    os.makedirs(os.path.dirname(child_lld), exist_ok=True)
                    shutil.copy2(source, child_lld)
                context_path = os.path.join(_run_dir(child_slug, root), "lld-context.json")
                if not os.path.exists(context_path):
                    _atomic_json(context_path, {
                        "schema_version": 2,
                        "slug": child_slug,
                        "step": "run-upgrade",
                        "context": "Imported legacy repository LLD; no new decisions recorded yet.",
                        "updated_at": statemod.now_iso(),
                        "rounds": [],
                        "decisions": [],
                    })
            if existing is None:
                resolver.init_run(child_slug, child_workflow, child_inputs, root)
        workstreams.append({"repo": repo, "slug": child_slug})
    queue = {
        "selected": selected,
        "remaining": list(selected),
        "workstreams": workstreams,
        "hld_sha256": hld_sha,
        "generation": 1,
    }
    with statemod.locked(parent, root):
        lld_repo_pool._save_queue(parent, root, queue)
    lines = [f"- `{item['repo']}` → `/maestro {item['slug']}`" for item in workstreams]
    manifest["status"] = "activated"
    manifest["activated_at"] = statemod.now_iso()
    manifest["workstreams"] = workstreams
    manifest["workstreams_md"] = "\n".join(lines)
    _atomic_json(full, manifest)
    return {
        "activated": True,
        "has_workstreams": bool(workstreams),
        "count": len(workstreams),
        "selected_csv": ",".join(selected),
        "hld_summary": "Validated imported HLD baseline",
        "workstreams_md": "\n".join(lines),
    }


def child_entry(slug, root):
    state = statemod.load(slug, root)
    if state is None:
        raise ValueError(f"child run {slug!r} does not exist")
    imported = (state.get("inputs") or {}).get("imported_lld") or ""
    full = imported if os.path.isabs(imported) else os.path.join(root, imported)
    return {"imported": bool(imported and os.path.isfile(full) and os.path.getsize(full) > 0)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".")
        p.add_argument("--slug", required=True)
        p.add_argument("--workflow", required=True)
    p = sub.add_parser("resume")
    p.add_argument("--root", default=".")
    p.add_argument("--manifest", default="")
    p = sub.add_parser("skip")
    p.add_argument("--root", default=".")
    p.add_argument("--manifest", required=True)
    p = sub.add_parser("activate")
    p.add_argument("--root", default=".")
    p.add_argument("--manifest", required=True)
    p.add_argument("--child-workflow", required=True)
    p = sub.add_parser("validate-baseline")
    p.add_argument("--root", default=".")
    p.add_argument("--manifest", required=True)
    p = sub.add_parser("child-entry")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect(args.slug, args.root, args.workflow)
        elif args.command == "apply":
            result = apply(args.slug, args.root, args.workflow)
        elif args.command == "resume":
            result = resume(args.manifest, args.root)
        elif args.command == "skip":
            result = skip(args.manifest, args.root)
        elif args.command == "activate":
            result = activate(args.manifest, args.root, args.child_workflow)
        elif args.command == "validate-baseline":
            result = validate_baseline(args.manifest, args.root)
        else:
            result = child_entry(args.slug, args.root)
    except (OSError, ValueError, KeyError, resolver.RunError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
