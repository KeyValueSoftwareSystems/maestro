#!/usr/bin/env python3
"""What a re-review should look at: the changes since the last review round, and that round's
findings — prepared by the engine before each review, so a reviewer re-checks the revision
instead of re-auditing the whole document.

  review_scope.py prepare --dir <reviews dir> --name <review> [--state-dir <dir>]
                          [--files a.md,b.md] [--findings F]

The engine keeps one baseline file per review, `<state dir>/<name>.baseline.json` (`--state-dir`,
else `--dir`): the text of each reviewed document as the last round saw it, and the ids of the
findings that round raised.

- `--files`: the reviewed documents. Each is diffed against its text in the baseline (unified
  diff, one file at `<state dir>/<name>.diff`), then the baseline is refreshed. The first round
  has no baseline, so it reviews everything. Omit it for code, where the reviewer diffs commits.
- `--findings`: the reviewer's findings file. The ids it holds now (the previous round's
  findings) go into the baseline for `findings.py verdict --previous <baseline>`, which flags
  blocking findings first raised on a re-review; with no findings file yet there was no round.

Prints one JSON line {rereview, diff_path, changed_csv, previous_findings, summary}; exit 0.
"""
import argparse
import difflib
import json
import os
import sys


def _read_lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines(keepends=True)
    except OSError:
        return None


def _load_baseline(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _finding_ids(path):
    """Ids in the findings file as it stands (the previous round's), or None without one."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return []
    items = doc.get("findings") if isinstance(doc, dict) else None
    return [item["id"] for item in items if isinstance(item, dict)
            and isinstance(item.get("id"), str)] if isinstance(items, list) else []


def prepare(directory, name, files=(), findings=None, state_dir=None):
    state_dir = state_dir or directory
    os.makedirs(directory, exist_ok=True)  # where the reviewer writes its report and findings
    os.makedirs(state_dir, exist_ok=True)
    baseline_path = os.path.join(state_dir, f"{name}.baseline.json")
    baseline = _load_baseline(baseline_path)
    kept = baseline.get("files") if isinstance(baseline.get("files"), dict) else None
    finding_ids = _finding_ids(findings)
    rereview = kept is not None or finding_ids is not None

    diff_path, changed, chunks = "", [], []
    if files:
        diff_path = os.path.join(state_dir, f"{name}.diff")
        current_text = {}
        for path in files:
            current = _read_lines(path)
            if current is None:
                continue
            current_text[path] = "".join(current)
            if kept is None:
                continue  # first round: everything is new, no diff to show
            before = kept[path].splitlines(keepends=True) if isinstance(kept.get(path), str) else []
            lines = list(difflib.unified_diff(before, current,
                                              fromfile=f"{path} (last review)", tofile=path))
            if lines:
                changed.append(path)
                chunks.append("".join(lines))
        with open(diff_path, "w", encoding="utf-8") as fh:
            if kept is None:
                fh.write("First review: no earlier version to compare against.\n")
            elif chunks:
                fh.write("\n".join(chunks))
            else:
                fh.write("No changes since the last review.\n")
        kept = {**(kept or {}), **current_text}

    if kept is None and finding_ids is None:
        if os.path.exists(baseline_path):
            os.remove(baseline_path)  # no round to compare with: drop a stale baseline
    else:
        tmp = f"{baseline_path}.tmp-{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "files": kept, "finding_ids": finding_ids}, fh,
                      indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, baseline_path)

    if not rereview:
        summary = "First review"
    elif files:
        summary = (f"Re-review: {len(changed)} file(s) changed since the last round"
                   + (f" ({', '.join(os.path.basename(p) for p in changed)})" if changed else ""))
    else:
        summary = "Re-review"
    return {"rereview": rereview, "diff_path": diff_path, "changed_csv": ",".join(changed),
            "previous_findings": baseline_path if finding_ids is not None else "",
            "summary": summary}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--dir", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--state-dir", help="where the baseline and diff are kept (default: --dir)")
    p.add_argument("--files", default="")
    p.add_argument("--findings")
    args = parser.parse_args(argv)
    files = [f.strip() for f in args.files.split(",") if f.strip()]
    print(json.dumps(prepare(args.dir, args.name, files, args.findings, args.state_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
