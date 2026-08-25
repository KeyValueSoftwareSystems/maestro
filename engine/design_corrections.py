#!/usr/bin/env python3
"""Approved design corrections and their deterministic effective-design context.

One immutable JSON receipt is written per human-approved correction.  Separate receipts avoid
the shared-file merge conflicts that appear when repository teams work in parallel.  ``render``
materialises a deterministic context consumed by every downstream phase.  ``prepare-fold`` and
``finalize-fold`` create and validate final corrected document copies during archive without
changing the originally approved, hash-bound design artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state as statemod  # noqa: E402
import validate_hld  # noqa: E402
import validate_lld  # noqa: E402
import validate_prd  # noqa: E402


SCOPES = ("product", "architecture", "repository", "contract", "verification", "cross-cutting")
SCHEMA_VERSION = 1


def _run_dir(slug, root):
    return statemod.feature_dir(slug, root)


def _approval_dir(slug, root):
    return os.path.join(_run_dir(slug, root), "approved-corrections")


def _context_path(slug, root):
    return os.path.join(_run_dir(slug, root), "approved-corrections.md")


def _manifest_path(slug, root):
    return os.path.join(_run_dir(slug, root), "effective-design.json")


def _fold_plan_path(slug, root):
    return os.path.join(_run_dir(slug, root), "correction-fold-plan.json")


def _fold_receipt_path(slug, root):
    return os.path.join(_run_dir(slug, root), "correction-fold.json")


def _atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=os.path.dirname(path), delete=False) as fh:
        tmp = fh.name
        fh.write(text)
        if not text.endswith("\n"):
            fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _write_json(path, document):
    _atomic_write(path, json.dumps(document, indent=2, sort_keys=True))


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _resolve_parent(slug, root, explicit_parent=None):
    if explicit_parent:
        parent = explicit_parent
    else:
        run = statemod.load(slug, root)
        if run is None:
            raise ValueError(f"run {slug!r} does not exist")
        parent = (run.get("inputs") or {}).get("parent_slug") or slug
    if not statemod.valid_slug(parent) or statemod.load(parent, root) is None:
        raise ValueError(f"parent run {parent!r} does not exist")
    return parent


def _artifact_paths(slug, root):
    run_dir = _run_dir(slug, root)
    candidates = [
        os.path.join(run_dir, "requirement", "prd.md"),
        os.path.join(run_dir, "hld.md"),
        os.path.join(run_dir, "openapi.yaml"),
        os.path.join(run_dir, "test-cases.md"),
    ]
    lld_dir = os.path.join(run_dir, "lld")
    if os.path.isdir(lld_dir):
        queue_path = os.path.join(run_dir, "lld-repos.json")
        try:
            selected = _load_json(queue_path).get("selected") or []
        except (OSError, ValueError, AttributeError):
            selected = []
        names = [f"{repo}.md" for repo in selected] if selected else sorted(os.listdir(lld_dir))
        candidates.extend(
            os.path.join(lld_dir, name) for name in names
            if name.endswith(".md") and os.path.isfile(os.path.join(lld_dir, name))
        )
    return [path for path in candidates if os.path.isfile(path) and os.path.getsize(path) > 0]


def _relative_artifact_hashes(slug, root):
    return {
        os.path.relpath(path, root): statemod.sha256_file(path)
        for path in _artifact_paths(slug, root)
    }


def _load_corrections(slug, root):
    directory = _approval_dir(slug, root)
    documents = []
    try:
        names = sorted(name for name in os.listdir(directory) if name.endswith(".json"))
    except OSError:
        return documents
    for name in names:
        path = os.path.join(directory, name)
        try:
            doc = _load_json(path)
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid approved correction {path}: {exc}") from None
        required = {"schema_version", "id", "parent_slug", "scope", "text", "approved_at"}
        if (not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION
                or not required.issubset(doc) or doc.get("parent_slug") != slug
                or doc.get("scope") not in SCOPES or not str(doc.get("text", "")).strip()
                or not isinstance(doc.get("id"), str)
                or doc.get("id") + ".json" != name):
            raise ValueError(f"invalid approved correction receipt {path}")
        documents.append(doc)
    return documents


def _render(slug, root):
    corrections = _load_corrections(slug, root)
    lines = [
        "# Approved corrections",
        "",
        "Engine-generated effective-design context. These human-approved decisions override any",
        "conflicting statement in the base PRD, HLD, repository LLDs, contract, or test cases.",
        "When no correction is listed, the approved base documents remain authoritative.",
    ]
    if not corrections:
        lines.extend(["", "None."])
    for item in corrections:
        lines.extend([
            "",
            f"## {item['id']}",
            "",
            f"- Scope: `{item['scope']}`",
            f"- Repository: `{item.get('repo') or 'all'}`",
            f"- Approved: `{item['approved_at']}`",
            f"- Source run: `{item.get('source_slug') or slug}`",
            "",
            item["text"].strip(),
        ])
    context_path = _context_path(slug, root)
    _atomic_write(context_path, "\n".join(lines))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "feature_slug": slug,
        "base_artifacts": _relative_artifact_hashes(slug, root),
        "corrections": [
            {
                "id": item["id"], "scope": item["scope"], "repo": item.get("repo"),
                "receipt": os.path.relpath(
                    os.path.join(_approval_dir(slug, root), item["id"] + ".json"), root,
                ),
            }
            for item in corrections
        ],
        "context_path": os.path.relpath(context_path, root),
        "context_sha256": statemod.sha256_file(context_path),
    }
    manifest_path = _manifest_path(slug, root)
    _write_json(manifest_path, manifest)
    return {
        "corrections_count": len(corrections),
        "corrections_path": os.path.relpath(context_path, root),
        "manifest_path": os.path.relpath(manifest_path, root),
        "manifest_sha256": statemod.sha256_file(manifest_path),
    }


def record(slug, root, scope, text, repo=None, parent_slug=None):
    parent = _resolve_parent(slug, root, explicit_parent=parent_slug)
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(SCOPES)}")
    text = text.strip()
    if not text:
        raise ValueError("correction text cannot be blank")
    if scope == "repository" and not repo:
        child = statemod.load(slug, root) or {}
        repo = (child.get("inputs") or {}).get("repo")
        if not repo:
            raise ValueError("repository corrections require --repo or a repository LLD child slug")
    if repo and (repo in (".", "..") or os.path.basename(repo) != repo or "/" in repo or "\\" in repo):
        raise ValueError("repository name must be one safe path segment")
    canonical = json.dumps(
        {"parent_slug": parent, "scope": scope, "repo": repo or "", "text": text},
        sort_keys=True, separators=(",", ":"),
    )
    correction_id = "CORR-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12].upper()
    path = os.path.join(_approval_dir(parent, root), correction_id + ".json")
    duplicate = os.path.exists(path)
    if duplicate:
        existing = _load_json(path)
        if any(existing.get(key) != value for key, value in (
                ("parent_slug", parent), ("scope", scope), ("repo", repo), ("text", text))):
            raise ValueError(f"correction id collision at {path}")
    else:
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "id": correction_id,
            "parent_slug": parent,
            "source_slug": slug,
            "scope": scope,
            "repo": repo,
            "text": text,
            "approved_at": statemod.now_iso(),
            "basis": _relative_artifact_hashes(parent, root),
        }
        _write_json(path, receipt)
    return {
        "ok": True, "duplicate": duplicate, "id": correction_id, "parent_slug": parent,
        "receipt_path": os.path.relpath(path, root),
        "corrections_dir": os.path.relpath(_approval_dir(parent, root), root),
        "corrections_count": len(_load_corrections(parent, root)),
    }


def _folded_ids(slug, root):
    path = _fold_receipt_path(slug, root)
    try:
        receipt = _load_json(path)
    except (OSError, ValueError):
        return set()
    return set(receipt.get("correction_ids") or [])


def _copy_target(source, run_dir, final_dir):
    rel = os.path.relpath(source, run_dir)
    if rel == os.path.join("requirement", "prd.md"):
        rel = "prd.md"
    target = os.path.join(final_dir, rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy2(source, target)
    return target


def prepare_fold(slug, root):
    rendered = _render(slug, root)
    corrections = _load_corrections(slug, root)
    pending = [item for item in corrections if item["id"] not in _folded_ids(slug, root)]
    if not pending:
        return {"pending": False, "pending_count": 0, "corrections_csv": "", **rendered}

    run_dir = _run_dir(slug, root)
    final_dir = os.path.join(run_dir, "final-design")
    plan_path = _fold_plan_path(slug, root)
    expected = {
        "correction_ids": [item["id"] for item in pending],
        "base_artifacts": _relative_artifact_hashes(slug, root),
    }
    if os.path.exists(plan_path):
        plan = _load_json(plan_path)
        if (plan.get("correction_ids") != expected["correction_ids"]
                or plan.get("base_artifacts") != expected["base_artifacts"]):
            raise ValueError(
                "correction fold inputs changed after preparation; remove the unfinished "
                "final-design fold only after reviewing those changes"
            )
    else:
        copied = []
        for source in _artifact_paths(slug, root):
            copied.append(os.path.relpath(_copy_target(source, run_dir, final_dir), root))
        open_questions = os.path.join(run_dir, "open-questions.json")
        if os.path.isfile(open_questions):
            copied.append(os.path.relpath(_copy_target(open_questions, run_dir, final_dir), root))
        plan = {
            "schema_version": SCHEMA_VERSION,
            "feature_slug": slug,
            **expected,
            "final_design_dir": os.path.relpath(final_dir, root),
            "copied_paths": copied,
            "prepared_at": statemod.now_iso(),
        }
        _write_json(plan_path, plan)
    return {
        "pending": True,
        "pending_count": len(pending),
        "corrections_csv": ",".join(item["id"] for item in pending),
        "corrections_path": rendered["corrections_path"],
        "fold_plan_path": os.path.relpath(plan_path, root),
        "final_design_dir": os.path.relpath(final_dir, root),
    }


def _required_fold_targets(item, slug, root):
    base = os.path.join(_run_dir(slug, root), "final-design")
    scope = item["scope"]
    if scope == "product":
        return [os.path.join(base, "prd.md")]
    if scope == "architecture":
        return [os.path.join(base, "hld.md")]
    if scope == "repository":
        return [os.path.join(base, "lld", f"{item.get('repo')}.md")]
    if scope == "contract":
        return [os.path.join(base, "openapi.yaml")]
    if scope == "verification":
        return [os.path.join(base, "test-cases.md")]
    return []


def _validate_final_design(slug, root, updated_paths):
    errors = []
    run_dir = _run_dir(slug, root)
    final_dir = os.path.join(run_dir, "final-design")
    prd = os.path.join(final_dir, "prd.md")
    if os.path.isfile(prd):
        found, _warnings = validate_prd.validate(prd)
        errors.extend(f"prd.md: {error}" for error in found)
    hld = os.path.join(final_dir, "hld.md")
    if os.path.isfile(hld):
        oq = os.path.join(final_dir, "open-questions.json")
        found, _warnings = validate_hld.validate(
            hld, open_questions_path=oq if os.path.isfile(oq) else None,
        )
        errors.extend(f"hld.md: {error}" for error in found)
    lld_dir = os.path.join(final_dir, "lld")
    if os.path.isdir(lld_dir):
        for name in sorted(os.listdir(lld_dir)):
            if not name.endswith(".md"):
                continue
            path = os.path.join(lld_dir, name)
            found, _warnings = validate_lld.validate(
                path, parent_slug=slug, repo=name[:-3],
            )
            errors.extend(f"lld/{name}: {error}" for error in found)
    if not updated_paths:
        errors.append("fold report must list at least one updated final-design path")
    return errors


def finalize_fold(slug, root, report_path):
    plan = _load_json(_fold_plan_path(slug, root))
    report = _load_json(report_path)
    expected_ids = plan.get("correction_ids") or []
    if (not isinstance(report, dict) or report.get("schema_version") != SCHEMA_VERSION
            or report.get("correction_ids") != expected_ids
            or not isinstance(report.get("updated_paths"), list)):
        raise ValueError("fold report must contain the exact planned correction_ids and updated_paths")
    run_dir = os.path.abspath(_run_dir(slug, root))
    final_dir = os.path.abspath(os.path.join(run_dir, "final-design"))
    updated = []
    for raw in report["updated_paths"]:
        path = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(root, raw))
        if os.path.commonpath([path, final_dir]) != final_dir or not os.path.isfile(path):
            raise ValueError(f"updated path must be an existing file under final-design: {raw}")
        updated.append(path)
    by_id = {item["id"]: item for item in _load_corrections(slug, root)}
    updated_set = set(updated)
    for correction_id in expected_ids:
        for target in _required_fold_targets(by_id[correction_id], slug, root):
            if target not in updated_set:
                raise ValueError(f"{correction_id} requires fold report path {os.path.relpath(target, root)}")
    errors = _validate_final_design(slug, root, updated)
    if errors:
        raise ValueError("final corrected documents failed validation: " + " | ".join(errors[:8]))
    result_hashes = {}
    for directory, _dirs, files in os.walk(final_dir):
        for name in sorted(files):
            path = os.path.join(directory, name)
            result_hashes[os.path.relpath(path, root)] = statemod.sha256_file(path)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "feature_slug": slug,
        "correction_ids": expected_ids,
        "result_artifacts": result_hashes,
        "report_path": os.path.relpath(report_path, root),
        "report_sha256": statemod.sha256_file(report_path),
        "folded_at": statemod.now_iso(),
    }
    receipt_path = _fold_receipt_path(slug, root)
    _write_json(receipt_path, receipt)
    return {
        "valid": True, "folded_count": len(expected_ids),
        "final_design_dir": os.path.relpath(final_dir, root),
        "fold_receipt_path": os.path.relpath(receipt_path, root),
    }


def _print(document):
    print(json.dumps(document, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("record")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--parent-slug")
    p.add_argument("--scope", required=True, choices=SCOPES)
    p.add_argument("--repo")
    p.add_argument("--text", required=True)

    p = sub.add_parser("render")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)

    p = sub.add_parser("prepare-fold")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)

    p = sub.add_parser("finalize-fold")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--report", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            result = record(
                args.slug, args.root, args.scope, args.text, repo=args.repo,
                parent_slug=args.parent_slug,
            )
        elif args.command == "render":
            parent = _resolve_parent(args.slug, args.root)
            result = _render(parent, args.root)
        elif args.command == "prepare-fold":
            result = prepare_fold(args.slug, args.root)
        else:
            result = finalize_fold(args.slug, args.root, args.report)
    except (OSError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    _print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
