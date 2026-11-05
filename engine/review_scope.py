#!/usr/bin/env python3
"""What a re-review should look at: the changes since the last review round, and that round's
findings — prepared by the engine before each review, so a reviewer re-checks the revision
instead of re-auditing the whole document.

  review_scope.py prepare --dir <reviews dir> --name <review> [--files a.md,b.md] [--findings F]

- `--files`: the reviewed documents. Each is diffed against the copy kept from the previous round
  (unified diff, one file at `<dir>/<name>.diff`), then the copy is refreshed. The first round has
  no copy, so it reviews everything. Omit it for code, where the reviewer diffs commits.
- `--findings`: the reviewer's findings file. Its current content (the previous round's
  findings) is kept as `<dir>/<name>-findings.previous.json` for `findings.py verdict
  --previous`, which flags blocking findings first raised on a re-review; with no findings file
  yet, any stale copy is removed.

Prints one JSON line {rereview, diff_path, changed_csv, previous_findings, summary}; exit 0.
"""
import argparse
import difflib
import json
import os
import shutil
import sys


def _snapshot_name(path):
    return path.replace(os.sep, "__").replace("/", "__")


def _read_lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines(keepends=True)
    except OSError:
        return None


def prepare(directory, name, files=(), findings=None):
    os.makedirs(directory, exist_ok=True)
    snapshots = os.path.join(directory, f".{name}-snapshot")
    rereview = os.path.isdir(snapshots)
    previous = os.path.join(directory, f"{name}-findings.previous.json")
    if findings and os.path.exists(findings):
        shutil.copyfile(findings, previous)
        rereview = True
    elif os.path.exists(previous):
        os.remove(previous)

    diff_path, changed, chunks = "", [], []
    if files:
        diff_path = os.path.join(directory, f"{name}.diff")
        for path in files:
            current = _read_lines(path)
            if current is None:
                continue
            kept = os.path.join(snapshots, _snapshot_name(path))
            before = _read_lines(kept) if os.path.isdir(snapshots) else None
            if before is None and not os.path.isdir(snapshots):
                continue  # first round: everything is new, no diff to show
            lines = list(difflib.unified_diff(before or [], current,
                                              fromfile=f"{path} (last review)", tofile=path))
            if lines:
                changed.append(path)
                chunks.append("".join(lines))
        with open(diff_path, "w", encoding="utf-8") as fh:
            if not os.path.isdir(snapshots):
                fh.write("First review: no earlier version to compare against.\n")
            elif chunks:
                fh.write("\n".join(chunks))
            else:
                fh.write("No changes since the last review.\n")
        os.makedirs(snapshots, exist_ok=True)
        for path in files:
            if os.path.isfile(path):
                shutil.copyfile(path, os.path.join(snapshots, _snapshot_name(path)))

    if not rereview:
        summary = "First review"
    elif files:
        summary = (f"Re-review: {len(changed)} file(s) changed since the last round"
                   + (f" ({', '.join(os.path.basename(p) for p in changed)})" if changed else ""))
    else:
        summary = "Re-review"
    return {"rereview": rereview, "diff_path": diff_path, "changed_csv": ",".join(changed),
            "previous_findings": previous if os.path.exists(previous) else "",
            "summary": summary}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--dir", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--files", default="")
    p.add_argument("--findings")
    args = parser.parse_args(argv)
    files = [f.strip() for f in args.files.split(",") if f.strip()]
    print(json.dumps(prepare(args.dir, args.name, files, args.findings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
