#!/usr/bin/env python3
"""Repo-scoped LLD workstreams — one independently approved child run per repository.

The parent feature selects real repositories discovered by codebase_scan. This helper creates a
durable child workflow for each selection, verifies its independent approval, and publishes an
LLD plus hash-bound receipt back to the parent. No repo team's gate can advance another team's
ledger. The older atomic claim command remains available for custom workflows.

Commands
--------
  list   [--root .]
      Discovered repo names (read-only). Prints {"names_csv", "count"}.

  init   [--root .] --slug <slug> --choice all|pick [--repos-text "..."]
      Validate the human's scope choice against the discovered repos and write the claim
      queue to .maestro/runs/<slug>/lld-repos.json. `pick` parses --repos-text as a
      comma/whitespace-separated list, case-insensitive, and fails on any name that doesn't
      match a discovered repo (never silently drops a typo). Prints {"selected_csv", "count"}.

  claim  [--root .] --slug <slug>
      Atomically pop the next unclaimed repo. Prints {"repo": "<name>", "done": false} or
      {"repo": "", "done": true} once the queue is empty.

  workstreams [--root .] --slug <parent> --workflow <path> [--feature <text>]
      Create or verify one child run per selected repo. Child slugs are stable and recorded in
      the parent's lld-repos.json; separate ledgers let repo teams work and approve in parallel.

  check [--root .] --slug <parent>
      Verify every selected child run completed and published a hash-matching approved LLD.

  validate-review [--root .] --slug <parent> --blocking <bool> --revision-scope <scope>
                  --repos-text <names> --correction-text <text>
      Validate and normalize the architecture review's deterministic revision routing fields.

  reopen [--root .] --slug <parent> --repos-text <names> --feedback <text>
         --workflow <path> [--feature <text>]
      Replace only the named approved child workstreams with fresh revision ledgers while keeping
      every unrelated repository approval intact.

  publish [--root .] --slug <child> --parent-slug <parent> --repo <name>
      After the child approval gate, atomically publish its LLD and approval receipt to the parent.
"""
import argparse
import hashlib
import json
import os
import re
import tempfile
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import state as statemod  # noqa: E402


REVIEW_SCOPES = ("product", "hld", "lld", "contract", "verification", "cross-cutting")


def _queue_path(slug, root):
    return os.path.join(statemod.feature_dir(slug, root), "lld-repos.json")


def _load_queue(slug, root):
    path = _queue_path(slug, root)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _save_queue(slug, root, doc):
    path = _queue_path(slug, root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


def _atomic_write(path, data, binary=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if binary else "w"
    kwargs = {} if binary else {"encoding": "utf-8"}
    with tempfile.NamedTemporaryFile(mode, dir=os.path.dirname(path), delete=False, **kwargs) as fh:
        tmp = fh.name
        fh.write(data)
        if not binary and not data.endswith("\n"):
            fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _repo_token(repo):
    token = re.sub(r"[^a-z0-9._-]+", "-", repo.lower()).strip("-._") or "repo"
    if token == repo.lower() and statemod.valid_slug(token):
        return token
    return f"{token}-{hashlib.sha256(repo.encode('utf-8')).hexdigest()[:8]}"


def _child_slug(parent_slug, repo, generation=1):
    revision = "" if generation == 1 else f"--v{generation}"
    suffix = f"--lld--{_repo_token(repo)}{revision}"
    candidate = parent_slug + suffix
    if len(candidate) <= 160:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:10]
    return parent_slug[:max(1, 160 - len(suffix) - 12)] + f"--{digest}" + suffix


def _approval_path(parent_slug, repo, root):
    return os.path.join(
        statemod.feature_dir(parent_slug, root), "lld-approvals", f"{repo}.json",
    )


def _published_lld_path(parent_slug, repo, root):
    return os.path.join(statemod.feature_dir(parent_slug, root), "lld", f"{repo}.md")


def cmd_list(args):
    names = [name for name, _path in codebase_scan.discover_repos(args.root)]
    print(json.dumps({"names_csv": ",".join(names), "count": len(names)}))
    return 0


def _parse_repos_text(text, discovered):
    by_lower = {n.lower(): n for n in discovered}
    wanted = [t.strip() for t in text.replace(",", " ").split() if t.strip()]
    picked, unknown = [], []
    for w in wanted:
        match = by_lower.get(w.lower())
        (picked if match else unknown).append(match or w)
    return picked, unknown


def _selected_repos(doc, text):
    selected = (doc or {}).get("selected") or []
    picked, unknown = _parse_repos_text(text or "", selected)
    picked = list(dict.fromkeys(picked))
    if unknown:
        raise ValueError(
            f"unknown affected repository name(s) {unknown}; selected repositories are {selected}"
        )
    if not picked:
        raise ValueError("at least one affected repository is required")
    return picked


def _child_generation(parent_slug, repo, child_slug):
    base = _child_slug(parent_slug, repo, 1)
    if child_slug == base:
        return 1
    match = re.match(re.escape(base) + r"--v(\d+)$", child_slug or "")
    return int(match.group(1)) if match else 1


def _next_child(slug, repo, root, after_generation):
    generation = max(2, after_generation + 1)
    while statemod.load(_child_slug(slug, repo, generation), root) is not None:
        generation += 1
    return _child_slug(slug, repo, generation), generation


def cmd_init(args):
    discovered = [name for name, _path in codebase_scan.discover_repos(args.root)]
    if not discovered:
        print(f"FAIL: no repos discovered under {args.root!r} (codebase/* or the root itself)",
              file=sys.stderr)
        return 1
    if args.choice == "all":
        selected = discovered
    else:
        if not args.repos_text:
            print("FAIL: --choice pick requires --repos-text", file=sys.stderr)
            return 1
        selected, unknown = _parse_repos_text(args.repos_text, discovered)
        if unknown:
            print(f"FAIL: unknown repo name(s) {unknown} — discovered repos are {discovered}",
                  file=sys.stderr)
            return 1
        if not selected:
            print("FAIL: no repos selected", file=sys.stderr)
            return 1
    with statemod.locked(args.slug, args.root):
        doc = _load_queue(args.slug, args.root) or {}
        doc["selected"] = selected
        doc["remaining"] = list(selected)
        if doc.get("workstreams"):
            doc["workstreams"] = [
                item for item in doc["workstreams"] if item.get("repo") in selected
            ]
        _save_queue(args.slug, args.root, doc)
    print(json.dumps({"selected_csv": ",".join(selected), "count": len(selected)}))
    return 0


def cmd_claim(args):
    with statemod.locked(args.slug, args.root):
        doc = _load_queue(args.slug, args.root)
        if doc is None:
            print(f"FAIL: no lld-repos.json for slug {args.slug!r} — run init first",
                  file=sys.stderr)
            return 1
        remaining = doc.get("remaining") or []
        if not remaining:
            print(json.dumps({"repo": "", "done": True}))
            return 0
        repo = remaining.pop(0)
        doc["remaining"] = remaining
        _save_queue(args.slug, args.root, doc)
    print(json.dumps({"repo": repo, "done": False}))
    return 0


def cmd_workstreams(args):
    import resolver

    doc = _load_queue(args.slug, args.root)
    if not doc or not doc.get("selected"):
        print(f"FAIL: no selected LLD repos for parent slug {args.slug!r}", file=sys.stderr)
        return 1
    parent_hld = os.path.join(statemod.feature_dir(args.slug, args.root), "hld.md")
    if not os.path.isfile(parent_hld):
        print(f"FAIL: approved parent HLD is missing for {args.slug!r}", file=sys.stderr)
        return 1
    hld_sha256 = statemod.sha256_file(parent_hld)
    previous_hld = doc.get("hld_sha256")
    generation = int(doc.get("generation") or 1)
    if previous_hld and previous_hld != hld_sha256:
        generation += 1
    existing_by_repo = {
        item.get("repo"): item for item in doc.get("workstreams", [])
        if isinstance(item, dict) and item.get("repo") and item.get("slug")
    } if not previous_hld or previous_hld == hld_sha256 else {}
    repo_paths = {
        name: os.path.relpath(path, args.root)
        for name, path in codebase_scan.discover_repos(args.root)
    }
    workstreams = []
    for repo in doc["selected"]:
        if repo not in repo_paths:
            print(f"FAIL: selected repository {repo!r} is no longer discoverable", file=sys.stderr)
            return 1
        existing_item = existing_by_repo.get(repo, {})
        child_generation = int(existing_item.get("generation") or generation)
        child_slug = existing_item.get("slug") or _child_slug(
            args.slug, repo, child_generation,
        )
        # A selective LLD revision may already own the numeric slug that a later HLD-wide
        # generation would normally choose. Never attach a new HLD to that older child ledger.
        if not existing_item and statemod.load(child_slug, args.root) is not None:
            child_slug, child_generation = _next_child(
                args.slug, repo, args.root, child_generation,
            )
        child_inputs = {
            "parent_slug": args.slug,
            "repo": repo,
            "repo_path": repo_paths[repo],
            "feature": args.feature or args.slug,
        }
        with statemod.locked(child_slug, args.root):
            existing = statemod.load(child_slug, args.root)
            if existing is not None:
                inputs = existing.get("inputs") or {}
                if (existing.get("workflow", {}).get("file") != args.workflow
                        or inputs.get("parent_slug") != args.slug or inputs.get("repo") != repo):
                    print(
                        f"FAIL: child slug {child_slug!r} already belongs to another workstream",
                        file=sys.stderr,
                    )
                    return 1
            else:
                resolver.init_run(
                    child_slug, args.workflow, child_inputs, args.root,
                )
        workstreams.append({
            "repo": repo, "slug": child_slug, "generation": child_generation,
        })
    doc["workstreams"] = workstreams
    doc["hld_sha256"] = hld_sha256
    doc["generation"] = max(item["generation"] for item in workstreams)
    with statemod.locked(args.slug, args.root):
        _save_queue(args.slug, args.root, doc)
    lines = [f"- `{item['repo']}` → `/maestro {item['slug']}`" for item in workstreams]
    print(json.dumps({
        "count": len(workstreams),
        "slugs_csv": ",".join(item["slug"] for item in workstreams),
        "workstreams_md": "\n".join(lines),
    }))
    return 0


def _published_ok(parent_slug, item, root):
    repo, child_slug = item["repo"], item["slug"]
    child = statemod.load(child_slug, root)
    if not child or child.get("run", {}).get("status") != "done":
        return False, "workstream not approved"
    approval_path = _approval_path(parent_slug, repo, root)
    lld_path = _published_lld_path(parent_slug, repo, root)
    try:
        with open(approval_path, encoding="utf-8") as fh:
            approval = json.load(fh)
    except (OSError, ValueError):
        return False, "approval receipt missing"
    if (approval.get("parent_slug") != parent_slug or approval.get("child_slug") != child_slug
            or approval.get("repo") != repo):
        return False, "approval receipt does not match workstream"
    if not os.path.isfile(lld_path):
        return False, "published LLD missing"
    if approval.get("sha256") != statemod.sha256_file(lld_path):
        return False, "published LLD changed after approval"
    parent_hld = os.path.join(statemod.feature_dir(parent_slug, root), "hld.md")
    if (not os.path.isfile(parent_hld)
            or approval.get("hld_sha256") != statemod.sha256_file(parent_hld)):
        return False, "parent HLD changed after approval"
    return True, "approved"


def cmd_check(args):
    doc = _load_queue(args.slug, args.root)
    workstreams = (doc or {}).get("workstreams") or []
    if not workstreams:
        print(f"FAIL: no LLD workstreams for parent slug {args.slug!r}", file=sys.stderr)
        return 1
    selected = (doc or {}).get("selected") or []
    if [item.get("repo") for item in workstreams] != selected:
        print("FAIL: LLD workstreams do not match the selected repository list", file=sys.stderr)
        return 1
    pending, statuses = [], []
    for item in workstreams:
        ok, reason = _published_ok(args.slug, item, args.root)
        statuses.append(f"- `{item['repo']}`: {'approved' if ok else reason} (`{item['slug']}`)")
        if not ok:
            pending.append(item["repo"])
    print(json.dumps({
        "ready": not pending,
        "approved_count": len(workstreams) - len(pending),
        "total_count": len(workstreams),
        "pending_csv": ",".join(pending),
        "status_md": "\n".join(statuses),
    }))
    return 0


def cmd_validate_review(args):
    blocking = str(args.blocking).strip().lower() == "true"
    if not blocking:
        print(json.dumps({
            "valid": True,
            "blocking": False,
            "revision_scope": "none",
            "affected_repos_csv": "",
            "correction_text": "",
        }))
        return 0
    scope = (args.revision_scope or "").strip().lower()
    if scope not in REVIEW_SCOPES:
        print(
            f"FAIL: blocking architecture review requires revision_scope in {REVIEW_SCOPES}",
            file=sys.stderr,
        )
        return 1
    correction = (args.correction_text or "").strip()
    if not correction:
        print("FAIL: blocking architecture review requires correction_text", file=sys.stderr)
        return 1
    try:
        repos = _selected_repos(_load_queue(args.slug, args.root), args.repos_text)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "valid": True,
        "blocking": True,
        "revision_scope": scope,
        "affected_repos_csv": ",".join(repos),
        "correction_text": correction,
    }))
    return 0


def cmd_reopen(args):
    import resolver

    doc = _load_queue(args.slug, args.root)
    if not doc or not doc.get("workstreams"):
        print(f"FAIL: no LLD workstreams for parent slug {args.slug!r}", file=sys.stderr)
        return 1
    try:
        repos = _selected_repos(doc, args.repos_text)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    feedback = (args.feedback or "").strip()
    if not feedback:
        print("FAIL: LLD revision feedback cannot be blank", file=sys.stderr)
        return 1
    parent_hld = os.path.join(statemod.feature_dir(args.slug, args.root), "hld.md")
    if (not os.path.isfile(parent_hld)
            or doc.get("hld_sha256") != statemod.sha256_file(parent_hld)):
        print(
            "FAIL: parent HLD changed; recreate all LLD workstreams from the HLD revision path",
            file=sys.stderr,
        )
        return 1
    repo_paths = {
        name: os.path.relpath(path, args.root)
        for name, path in codebase_scan.discover_repos(args.root)
    }
    by_repo = {
        item.get("repo"): dict(item)
        for item in doc.get("workstreams") or []
        if isinstance(item, dict) and item.get("repo") and item.get("slug")
    }
    for repo in repos:
        if repo not in by_repo or repo not in repo_paths:
            print(f"FAIL: affected repository {repo!r} has no current workstream", file=sys.stderr)
            return 1

    reopened = []
    for repo in repos:
        current = by_repo[repo]
        current_state = statemod.load(current["slug"], args.root) or {}
        current_inputs = current_state.get("inputs") or {}
        if (current_state.get("run", {}).get("status") == "running"
                and current_inputs.get("review_feedback") == feedback):
            reopened.append(current)
            continue
        if current_state.get("run", {}).get("status") != "done":
            print(
                f"FAIL: repository {repo!r} already has an unfinished LLD workstream",
                file=sys.stderr,
            )
            return 1
        generation = int(current.get("generation") or _child_generation(
            args.slug, repo, current["slug"],
        ))
        child_slug, generation = _next_child(args.slug, repo, args.root, generation)
        child_inputs = {
            "parent_slug": args.slug,
            "repo": repo,
            "repo_path": repo_paths[repo],
            "feature": args.feature or args.slug,
            "review_feedback": feedback,
        }
        with statemod.locked(child_slug, args.root):
            resolver.init_run(child_slug, args.workflow, child_inputs, args.root)
        replacement = {"repo": repo, "slug": child_slug, "generation": generation}
        by_repo[repo] = replacement
        reopened.append(replacement)

    doc["workstreams"] = [by_repo[repo] for repo in doc["selected"]]
    doc["generation"] = max(
        int(item.get("generation") or _child_generation(args.slug, item["repo"], item["slug"]))
        for item in doc["workstreams"]
    )
    with statemod.locked(args.slug, args.root):
        _save_queue(args.slug, args.root, doc)
    lines = [f"- `{item['repo']}` → `/maestro {item['slug']}`" for item in reopened]
    print(json.dumps({
        "reopened_count": len(reopened),
        "reopened_repos_csv": ",".join(item["repo"] for item in reopened),
        "workstreams_md": "\n".join(lines),
        "hld_summary": (
            "Existing approved PRD/HLD retained; reopened LLDs for "
            + ", ".join(item["repo"] for item in reopened)
        ),
    }))
    return 0


def workstream_summary(slug, root="."):
    """Read-only resume picker data for a parent feature or one of its LLD children."""
    selected = statemod.load(slug, root)
    if selected is None:
        return {"available": False, "parent_slug": slug, "workstreams": []}
    selected_inputs = selected.get("inputs") or {}
    parent_slug = selected_inputs.get("parent_slug") or slug
    parent = statemod.load(parent_slug, root)
    doc = _load_queue(parent_slug, root) or {}
    items = []
    for item in doc.get("workstreams") or []:
        child = statemod.load(item.get("slug", ""), root)
        ok, reason = _published_ok(parent_slug, item, root)
        run = (child or {}).get("run") or {}
        items.append({
            "slug": item.get("slug"),
            "repo": item.get("repo"),
            "workflow": (child or {}).get("workflow", {}).get("file"),
            "status": "approved" if ok else (run.get("status") or "missing"),
            "detail": reason,
            "active": run.get("cursors") or [],
        })
    parent_active = ((parent or {}).get("run") or {}).get("cursors") or []
    waiting = any(path.endswith("lld_workstreams_wait") for path in parent_active)
    return {
        "available": bool(items) and waiting,
        "parent_slug": parent_slug,
        "parent_status": ((parent or {}).get("run") or {}).get("status"),
        "parent_active": parent_active,
        "selected_slug": slug,
        "workstreams": items,
    }


def cmd_publish(args):
    child = statemod.load(args.slug, args.root)
    if child is None:
        print(f"FAIL: child run {args.slug!r} does not exist", file=sys.stderr)
        return 1
    inputs = child.get("inputs") or {}
    if inputs.get("parent_slug") != args.parent_slug or inputs.get("repo") != args.repo:
        print("FAIL: child run inputs do not match parent/repo", file=sys.stderr)
        return 1
    approvals = [
        gate for gate in child.get("gates", [])
        if gate.get("step") == "lld_approval" and gate.get("option") == "approve"
    ]
    if not approvals:
        print("FAIL: LLD has not passed its child approval gate", file=sys.stderr)
        return 1
    parent_queue = _load_queue(args.parent_slug, args.root) or {}
    mapped = next(
        (item for item in parent_queue.get("workstreams", []) if item.get("repo") == args.repo),
        None,
    )
    if not mapped or mapped.get("slug") != args.slug:
        print("FAIL: parent does not map this repo to the publishing child run", file=sys.stderr)
        return 1
    parent_hld = os.path.join(statemod.feature_dir(args.parent_slug, args.root), "hld.md")
    if (not os.path.isfile(parent_hld)
            or parent_queue.get("hld_sha256") != statemod.sha256_file(parent_hld)):
        print(
            "FAIL: parent HLD changed after this child workstream was created; "
            "refresh the parent to create a new LLD generation",
            file=sys.stderr,
        )
        return 1
    source = os.path.join(statemod.feature_dir(args.slug, args.root), "lld.md")
    try:
        with open(source, "rb") as fh:
            content = fh.read()
    except OSError as exc:
        print(f"FAIL: cannot read child LLD: {exc}", file=sys.stderr)
        return 1
    if not content.strip():
        print("FAIL: child LLD is empty", file=sys.stderr)
        return 1
    target = _published_lld_path(args.parent_slug, args.repo, args.root)
    approval_path = _approval_path(args.parent_slug, args.repo, args.root)
    with statemod.locked(args.parent_slug, args.root):
        _atomic_write(target, content, binary=True)
        digest = statemod.sha256_file(target)
        receipt = {
            "version": 1,
            "parent_slug": args.parent_slug,
            "child_slug": args.slug,
            "repo": args.repo,
            "sha256": digest,
            "hld_sha256": statemod.sha256_file(parent_hld),
            "approved_at": approvals[-1].get("at"),
            "published_at": statemod.now_iso(),
        }
        _atomic_write(approval_path, json.dumps(receipt, indent=2))
    print(json.dumps({
        "lld_path": os.path.relpath(target, args.root),
        "approval_path": os.path.relpath(approval_path, args.root),
        "sha256": digest,
    }))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list")
    p.add_argument("--root", default=".")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("init")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--choice", required=True, choices=["all", "pick"])
    p.add_argument("--repos-text", default="")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("claim")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.set_defaults(fn=cmd_claim)

    p = sub.add_parser("workstreams")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True, help="parent feature slug")
    p.add_argument("--workflow", required=True, help="repo LLD child workflow")
    p.add_argument("--feature", default="")
    p.set_defaults(fn=cmd_workstreams)

    p = sub.add_parser("check")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True, help="parent feature slug")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("validate-review")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True, help="parent feature slug")
    p.add_argument("--blocking", required=True)
    p.add_argument("--revision-scope", default="")
    p.add_argument("--repos-text", default="")
    p.add_argument("--correction-text", default="")
    p.set_defaults(fn=cmd_validate_review)

    p = sub.add_parser("reopen")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True, help="parent feature slug")
    p.add_argument("--repos-text", required=True)
    p.add_argument("--feedback", required=True)
    p.add_argument("--workflow", required=True, help="repo LLD child workflow")
    p.add_argument("--feature", default="")
    p.set_defaults(fn=cmd_reopen)

    p = sub.add_parser("publish")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True, help="child LLD workstream slug")
    p.add_argument("--parent-slug", required=True)
    p.add_argument("--repo", required=True)
    p.set_defaults(fn=cmd_publish)

    args = parser.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
