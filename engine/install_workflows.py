#!/usr/bin/env python3
"""Upgrade a consumer's installed workflows without overwriting their edits.

install.sh calls this instead of copying workflows/ over .maestro/workflows/. Each
upstream file is classified by comparing the local copy against what Maestro has
shipped before:

  * the install manifest (.maestro/workflow-manifest.json) — the version offered by the
    previous install of THIS repo;
  * the release list (workflow_releases.json, beside this module) — every version the
    pack has ever shipped, so a repo installed before the manifest existed is still
    recognised as untouched.

Rules, per upstream file:

  missing locally                       -> added   (copy upstream)
  local == upstream                     -> current (nothing to do)
  local matches manifest or a release   -> updated (stock copy: replace)
  edited, upstream changed since offer  -> review  (keep local, write <name>.upstream)
  edited, upstream unchanged            -> kept    (keep local; any pending .upstream stays)

A local edit is NEVER written to. Comparison is strict — the exact file bytes (line
endings normalised) — so ANY change, including comments, formatting or a re-save from
the builder, counts as an edit. Only a byte-identical stock copy is ever replaced, so
nothing is lost and no backup is kept. Files the user added under their own names are
never touched. Files upstream stopped shipping are reported, never deleted. After a
real install every workflow is validated and failures are reported (they never abort
the install).

Usage: install_workflows.py --src <pack>/workflows --root <consumer repo> [--dry-run]
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RELEASES = os.path.join(HERE, "workflow_releases.json")
MANIFEST_REL = os.path.join(".maestro", "workflow-manifest.json")
DEST_REL = os.path.join(".maestro", "workflows")
UPSTREAM_SUFFIX = ".upstream"


def content_hash(data, name=None):
    """Strict identity of a file: its exact bytes. CRLF is folded to LF only so a
    git checkout with autocrlf is not mistaken for an edit."""
    return "sha256:" + hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def _write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def plan(src, root, releases):
    """Classify every upstream file. -> (actions, retired, manifest_out). Pure: no writes."""
    dest = os.path.join(root, DEST_REL)
    manifest_doc = _load_json(os.path.join(root, MANIFEST_REL), None)
    manifest = (manifest_doc or {}).get("files") or {}
    known = releases.get("files") or {}

    names = sorted(n for n in os.listdir(src) if os.path.isfile(os.path.join(src, n)))
    actions, manifest_out = [], {}
    for name in names:
        new = _read(os.path.join(src, name))
        new_hash = content_hash(new, name)
        manifest_out[name] = new_hash
        local_path = os.path.join(dest, name)
        if not os.path.isfile(local_path):
            actions.append((name, "added", new))
            continue
        local = _read(local_path)
        local_hash = content_hash(local, name)
        if local_hash == new_hash:
            actions.append((name, "current", new))
        elif local_hash == manifest.get(name) or local_hash in (known.get(name) or ()):
            actions.append((name, "updated", new))
        elif manifest.get(name) == new_hash:
            actions.append((name, "kept", new))
        else:
            actions.append((name, "review", new))

    # Report what upstream stopped shipping. With a manifest, only what it last offered;
    # before the first manifest, any historic name the user still has.
    previous = manifest if manifest_doc is not None else known
    retired = sorted(n for n in previous if n not in manifest_out
                     and os.path.isfile(os.path.join(dest, n)))
    return actions, retired, manifest_out


def apply(actions, manifest_out, root):
    dest = os.path.join(root, DEST_REL)
    for name, action, new in actions:
        local_path = os.path.join(dest, name)
        pending = local_path + UPSTREAM_SUFFIX
        if action in ("added", "updated"):
            _write_atomic(local_path, new)
        elif action == "review":
            _write_atomic(pending, new)
        # A stock (or now-identical) file has nothing left to reconcile.
        if action in ("added", "updated", "current") and os.path.isfile(pending):
            os.remove(pending)
    manifest = {"version": 1, "files": manifest_out}
    _write_atomic(os.path.join(root, MANIFEST_REL),
                  (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def validate_all(root):
    """-> [(file, [error strings])] for every installed workflow that fails validation."""
    import validate as validatemod
    dest = os.path.join(root, DEST_REL)
    failures = []
    for name in sorted(os.listdir(dest)):
        if not name.endswith((".yaml", ".yml")):
            continue
        rel = os.path.join(DEST_REL, name)
        errors = [str(i) for i in validatemod.validate_file(rel, root=root) if i.level == "error"]
        if errors:
            failures.append((rel, errors))
    return failures


LABELS = {
    "added": "added",
    "updated": "updated (stock copy replaced)",
    "current": "up to date",
    "kept": "kept your edits (no upstream change)",
    "review": "kept your edits — upstream changed, see",
}


def report(actions, retired, dry_run, failures):
    out = []
    head = "Workflow upgrade plan (dry run — nothing written)" if dry_run else "Workflows"
    out.append(f"  {head}:")
    for name, action, _ in actions:
        label = LABELS[action]
        if action == "review":
            label += f" .maestro/workflows/{name}{UPSTREAM_SUFFIX}"
        out.append(f"    {name:<24} {label}")
    for name in retired:
        out.append(f"    {name:<24} no longer shipped upstream — left in place")
    if any(a == "review" for _, a, _ in actions):
        out.append("  Reconcile each *.upstream into your file (or `mv` it over yours to take "
                   "upstream), then delete it.")
    for rel, errors in failures:
        out.append(f"  ! {rel} fails validation ({len(errors)} error(s)), e.g. {errors[0]}")
    print("\n".join(out))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--src", required=True, help="the pack's workflows/ directory")
    ap.add_argument("--root", required=True, help="consumer repo root")
    ap.add_argument("--releases", default=RELEASES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    dest = os.path.join(root, DEST_REL)
    if os.path.isdir(dest) and os.path.samefile(args.src, dest):
        print("  .maestro/workflows is the pack source itself — nothing to upgrade")
        return 0
    actions, retired, manifest_out = plan(args.src, root, _load_json(args.releases, {}))
    failures = []
    if not args.dry_run:
        apply(actions, manifest_out, root)
        failures = validate_all(root)
    report(actions, retired, args.dry_run, failures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
