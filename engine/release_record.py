#!/usr/bin/env python3
"""The feature's release record: proof that the release gate approved exactly this manifest.

  release_record.py record [--root .] --slug S --manifest M [--by person|autopilot]
  release_record.py check  [--root .] --slug S --manifest M

record  after the release gate approves: writes release.json in the feature folder (who
        approved, when, the manifest's path and sha256).
check   before the archive: the record must exist and bind the manifest as it is now, so an
        unapproved feature, or one rebuilt since the approval, is never delivered. Returns who
        approved (`release_by`), which makes a later standalone archive open draft pull requests
        for an autopilot release too.

stdout: one JSON object; a refusal goes to stderr with exit 1.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state as statemod  # noqa: E402

FILE = "release.json"


def record_path(slug, root="."):
    return os.path.join(statemod.feature_dir(slug, root), FILE)


def _manifest_hash(root, manifest):
    full = os.path.join(root, manifest)
    if not os.path.isfile(full):
        raise RuntimeError(f"implementation manifest not found: {manifest} — the feature has not "
                           "been through implementation, QA and release approval")
    return statemod.sha256_file(full)


def record(args):
    digest = _manifest_hash(args.root, args.manifest)
    by = "autopilot" if args.by == "autopilot" else "person"
    path = record_path(args.slug, args.root)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": 1, "approved_by": by, "approved_at": statemod.now_iso(),
                   "manifest": args.manifest, "manifest_sha256": digest}, fh, indent=2)
        fh.write("\n")
    return {"path": os.path.relpath(path, args.root), "release_by": by,
            "summary": f"Release approved by {by}"}


def check(args):
    path = record_path(args.slug, args.root)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise RuntimeError(f"no release approval is recorded for {args.slug!r}: run the feature "
                           "through release approval first") from None
    except ValueError:
        raise RuntimeError(f"{os.path.relpath(path, args.root)} is not readable JSON") from None
    if not isinstance(data, dict) or data.get("approved_by") not in ("person", "autopilot"):
        raise RuntimeError(f"{os.path.relpath(path, args.root)} is not a release record")
    if data.get("manifest_sha256") != _manifest_hash(args.root, args.manifest):
        raise RuntimeError("the implementation manifest changed after the release was approved: "
                           "approve the release again")
    by = data["approved_by"]
    return {"release_by": by, "approved_at": data.get("approved_at", ""),
            "summary": f"Release approved by {by}"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "check"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--root", default=".")
        cmd.add_argument("--slug", required=True)
        cmd.add_argument("--manifest", required=True)
        if name == "record":
            cmd.add_argument("--by", default="person")
    args = parser.parse_args(argv)
    try:
        result = record(args) if args.command == "record" else check(args)
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
