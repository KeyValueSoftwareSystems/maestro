#!/usr/bin/env python3
"""Regenerate engine/workflow_releases.json — the content hash of every version of every
workflows/* file this pack has ever shipped (git history + the working tree).

install_workflows.py uses it to recognise an unedited stock copy from any past release,
so upgrading a repo never mistakes it for a user edit. Run after editing workflows/:

    python3 scripts/gen_workflow_releases.py           # rewrite (union with existing)
    python3 scripts/gen_workflow_releases.py --check   # exit 1 if a hash is missing

Writing is a UNION with the existing file, so a shallow clone never drops history.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from install_workflows import content_hash  # noqa: E402

OUT = os.path.join(ROOT, "engine", "workflow_releases.json")
WF_DIR = "workflows"


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout


def collect():
    """-> {name: set(hash)} from every commit touching workflows/ plus the working tree."""
    found = {}

    def add(name, data):
        found.setdefault(name, set()).add(content_hash(data, name))

    try:
        commits = _git("rev-list", "HEAD", "--", WF_DIR).decode().split()
    except (OSError, subprocess.CalledProcessError):
        commits = []
    for commit in commits:
        try:
            listing = _git("ls-tree", f"{commit}:{WF_DIR}").decode().splitlines()
        except subprocess.CalledProcessError:
            continue  # the commit that removed workflows/ entirely
        for line in listing:
            meta, name = line.split("\t", 1)
            if meta.split()[1] == "blob":  # sub-directories were never installed as files
                add(name, _git("show", f"{commit}:{WF_DIR}/{name}"))
    src = os.path.join(ROOT, WF_DIR)
    for name in os.listdir(src):
        path = os.path.join(src, name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                add(name, fh.read())
    return found


def load():
    try:
        with open(OUT, encoding="utf-8") as fh:
            return {k: set(v) for k, v in json.load(fh).get("files", {}).items()}
    except (OSError, ValueError):
        return {}


def main(argv):
    existing, found = load(), collect()
    missing = {n: sorted(h - existing.get(n, set())) for n, h in found.items()}
    missing = {n: h for n, h in missing.items() if h}
    if "--check" in argv:
        if missing:
            print(f"{os.path.relpath(OUT, ROOT)} is stale for: {', '.join(sorted(missing))}. "
                  "Run: python3 scripts/gen_workflow_releases.py", file=sys.stderr)
            return 1
        return 0
    merged = {n: sorted(existing.get(n, set()) | found.get(n, set()))
              for n in sorted(set(existing) | set(found))}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "files": merged}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {os.path.relpath(OUT, ROOT)}: {sum(map(len, merged.values()))} hashes, "
          f"{len(merged)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
