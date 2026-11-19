#!/usr/bin/env python3
"""The team's own documents: protected from the docs writers, and first in priority.

People drop their own documents into the workspace (a product spec, a domain write-up, an
exported wiki page). Those are SOURCE docs: every file under docs/ that Maestro does not write,
plus whatever `docs.sources` in maestro.config.yaml lists (globs from the workspace root, e.g.
`specs/**`). Maestro writes only the living docs (docs/architecture.md and the docs/<domain>.md
files with `doc:` front-matter), the generated files, docs/codebase-maps/ and docs/provenance.yaml;
docs/impact/side-effects.yaml is the team's and locked by living_docs.py (R9).

A writer step may ADD to a source doc (every original line kept, in order). Anything else (a line
changed or removed, the file deleted, a binary touched) is a rewrite: the engine puts the original
back and keeps the writer's version as a proposal, and a person decides. Where the writer finds the
code disagreeing with a source doc, it follows the source doc and reports the conflict; a person
decides those too. Nothing here relies on the writer obeying its instructions.

  source_docs.py list     [--root .]
      {count, paths_csv}
  source_docs.py snapshot [--root .] --out DIR
      copies every source doc into DIR (git-ignored) before a writer starts; clears earlier
      proposals. Fails when docs/architecture.md was written by people (Maestro's path).
  source_docs.py guard    [--root .] --snapshot DIR [--conflicts JSON] [--report MD]
      the writer's handoff check: restores rewrites (kept under DIR/proposed/), validates the
      writer's conflict list, refuses new files under docs/ that are not living docs, and writes
      the person's report. {valid, source_conflicts, has_source_conflicts, source_additions, ...}
  source_docs.py review   --snapshot DIR
      route-only: {has_source_conflicts, source_conflicts, proposal_count, summary}
  source_docs.py apply    [--root .] --snapshot DIR
      a person approved the proposals: write each one over its source doc, only where the source
      is still exactly as snapshotted. {applied, skipped, summary}

The writer's conflict list (JSON): {"conflicts": [{"source": "<path>", "source_says": "...",
"code_says": "...", "evidence": "repo · path · symbol", "doc": "docs/<domain>.md"}]}.
"""
import argparse
import difflib
import glob
import hashlib
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_config  # noqa: E402

OWNED_FILES = {"docs/architecture.mmd", "docs/code-to-facts.md", "docs/provenance.yaml",
               "docs/impact/side-effects.yaml"}
OWNED_DIRS = ("docs/codebase-maps/",)
LEGACY_DIRS = ("docs/functional/", "docs/technical/", "docs/_generated/", "docs/_index/")
SKIP_PARTS = {".git", ".maestro", "node_modules", "__pycache__"}
MANIFEST = "manifest.json"
PROPOSALS = "proposals.json"
CONFLICTS = "conflicts.json"
SUMMARY_LINES = 8


# --------------------------------------------------------------------------- which files

def _rel(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _doc_kind(path):
    """The `doc:` front-matter value of a Markdown file, or None."""
    try:
        with open(path, encoding="utf-8") as fh:
            head = fh.read(4096)
    except (OSError, UnicodeDecodeError):
        return None
    match = re.match(r"---\n(.*?)\n---\n", head, re.S)
    if not match:
        return None
    kind = re.search(r"^doc:\s*['\"]?([\w-]+)", match.group(1), re.M)
    return kind.group(1) if kind else None


def _maestro_built(root):
    """Maestro has built docs here before (provenance, or the old layout it migrates)."""
    return (os.path.isfile(os.path.join(root, "docs", "provenance.yaml"))
            or any(os.path.isdir(os.path.join(root, d)) for d in LEGACY_DIRS))


def is_owned(root, rel):
    """True for a file Maestro writes (so not a source doc)."""
    if rel in OWNED_FILES or rel.startswith(OWNED_DIRS) or rel.startswith(LEGACY_DIRS):
        return True
    parts = rel.split("/")
    if len(parts) == 2 and parts[0] == "docs" and rel.endswith(".md"):
        kind = _doc_kind(os.path.join(root, rel))
        if kind in ("architecture", "domain"):
            return True
        if rel == "docs/architecture.md":
            return _maestro_built(root)
    return False


def _hidden(rel):
    return any(p.startswith(".") or p in SKIP_PARTS for p in rel.split("/"))


def _config_globs(root):
    try:
        config = project_config.load(root) or {}
    except project_config.ConfigError:
        config = {}
    docs = config.get("docs") if isinstance(config, dict) else None
    sources = (docs or {}).get("sources") if isinstance(docs, dict) else None
    return [g for g in sources if isinstance(g, str) and g.strip()] if isinstance(sources, list) else []


def source_paths(root):
    """Workspace-relative paths of every source doc, sorted."""
    found = set()
    base = os.path.join(root, "docs")
    if os.path.isdir(base):
        for folder, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_PARTS)
            for name in files:
                rel = _rel(root, os.path.join(folder, name))
                if not _hidden(rel) and not is_owned(root, rel):
                    found.add(rel)
    for pattern in _config_globs(root):
        for path in glob.glob(os.path.join(root, pattern), recursive=True):
            rel = _rel(root, path)
            if os.path.isfile(path) and not rel.startswith("..") and not _hidden(rel) \
                    and not is_owned(root, rel):
                found.add(rel)
    return sorted(found)


# --------------------------------------------------------------------------- snapshot

def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _text(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        if b"\0" in data:
            return None
        return data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _dump(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def snapshot(root, out):
    arch = os.path.join(root, "docs", "architecture.md")
    if os.path.isfile(arch) and not is_owned(root, "docs/architecture.md"):
        raise SystemExit(
            "docs/architecture.md was written by people (it has no `doc: architecture` "
            "front-matter), and Maestro writes its architecture doc at that path. Move it, for "
            "example to docs/product/architecture.md: Maestro then reads it as a source doc, "
            "follows it, and never rewrites it.")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "files"))
    with open(os.path.join(out, ".gitignore"), "w", encoding="utf-8") as fh:
        fh.write("# copies of the team's source docs, kept only to restore them\n*\n")
    manifest = {}
    for rel in source_paths(root):
        src = os.path.join(root, rel)
        dst = os.path.join(out, "files", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        manifest[rel] = {"sha256": _sha_file(src), "text": _text(src) is not None}
    _dump(os.path.join(out, MANIFEST), {"files": manifest})
    return {"count": len(manifest), "paths_csv": ",".join(manifest), "snapshot": out}


# --------------------------------------------------------------------------- guard

def _additive(old, new):
    """Every original line kept, in order: only insertions."""
    ops = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False).get_opcodes()
    return all(tag in ("equal", "insert") for tag, *_ in ops)


def _diff(old, new, rel):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"{rel} (yours)", f"{rel} (proposed)"))


def _restore(snap, root, rel):
    dst = os.path.join(root, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(os.path.join(snap, "files", rel), dst)


def _stage(snap, root, rel, kind, files):
    """Keep the writer's version of a rewritten source doc as a proposal, and put the original back."""
    proposals = _load(os.path.join(snap, PROPOSALS), {})
    entry = {"kind": kind}
    if kind == "rewrite":
        staged = os.path.join(snap, "proposed", rel)
        os.makedirs(os.path.dirname(staged), exist_ok=True)
        shutil.copy2(os.path.join(root, rel), staged)
        old, new = _text(os.path.join(snap, "files", rel)), _text(staged)
        if files[rel]["text"] and new is not None:
            entry["diff"] = _diff(old, new, rel)
    proposals[rel] = entry
    _dump(os.path.join(snap, PROPOSALS), proposals)
    _restore(snap, root, rel)


def _check_reported(path, sources):
    """The writer's conflict list: (conflicts, issues)."""
    if not path or not os.path.isfile(path):
        return [], []
    data = _load(path, None)
    if not isinstance(data, dict) or not isinstance(data.get("conflicts"), list):
        return [], [f"{path}: must be a JSON object with a `conflicts` list"]
    keep, issues = [], []
    for i, item in enumerate(data["conflicts"]):
        where = f"{path} conflicts[{i}]"
        if not isinstance(item, dict):
            issues.append(f"{where}: must be an object")
            continue
        missing = [k for k in ("source", "source_says", "code_says", "evidence")
                   if not isinstance(item.get(k), str) or not item[k].strip()]
        if missing:
            issues.append(f"{where}: needs {', '.join(missing)}")
            continue
        if item["source"] not in sources:
            issues.append(f"{where}: `{item['source']}` is not one of the team's source docs "
                          f"({', '.join(sorted(sources)) or 'none'})")
            continue
        keep.append({k: item[k].strip() for k in ("source", "source_says", "code_says", "evidence")}
                    | {"doc": str(item.get("doc") or "").strip()})
    return keep, issues


def _new_strays(root, files):
    """Files under docs/ the step created that are neither living docs nor a source doc before."""
    base = os.path.join(root, "docs")
    strays = []
    if os.path.isdir(base):
        for folder, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in names:
                rel = _rel(root, os.path.join(folder, name))
                if rel not in files and not _hidden(rel) and not is_owned(root, rel):
                    strays.append(rel)
    return sorted(strays)


def _render(path, record):
    lines = ["# Conflicts with the team's source docs", "",
             "Maestro never rewrites a document your team put in the workspace. Below is what it",
             "would change, and where the code disagrees with your documents. The living docs follow",
             "your documents until you decide.", ""]
    if record["reported"]:
        lines += ["## Where the code disagrees with your documents", ""]
        for c in record["reported"]:
            lines += [f"- **{c['source']}** says: {c['source_says']}",
                      f"  - The code: {c['code_says']} ({c['evidence']})"]
            if c.get("doc"):
                lines.append(f"  - Noted in {c['doc']} under Open questions and known gaps.")
        lines.append("")
    if record["proposals"]:
        lines += ["## Edits Maestro proposes to your documents (not applied)", ""]
        for rel, p in sorted(record["proposals"].items()):
            if p["kind"] == "delete":
                lines.append(f"- **{rel}**: the writer removed it. It has been put back.")
            elif p.get("diff"):
                lines += [f"- **{rel}**: changed text. It has been put back; the proposed change:",
                          "", "```diff", p["diff"].rstrip("\n"), "```", ""]
            else:
                lines.append(f"- **{rel}**: the writer changed this file. It has been put back.")
        lines.append("")
    if record["additions"]:
        lines += ["## Added to your documents (kept; nothing of yours was changed)", ""]
        lines += [f"- {rel}" for rel in record["additions"]] + [""]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip("\n") + "\n")


def summary(record, report=None):
    items = [f"- {c['source']}: it says {c['source_says']}; the code: {c['code_says']}"
             for c in record["reported"]]
    items += [f"- {rel}: the writer {'removed' if p['kind'] == 'delete' else 'rewrote'} it "
              "(put back; its version is a proposal)" for rel, p in sorted(record["proposals"].items())]
    shown = items[:SUMMARY_LINES]
    if len(items) > SUMMARY_LINES:
        shown.append(f"- … and {len(items) - SUMMARY_LINES} more")
    if report:
        shown.append(f"Full report: {report}")
    return "\n".join(shown)


def guard(root, snap, conflicts_path=None, report=None):
    manifest = _load(os.path.join(snap, MANIFEST), None)
    if not isinstance(manifest, dict):
        raise SystemExit(f"{snap}/{MANIFEST} is missing: run `source_docs.py snapshot` first")
    files = manifest.get("files") or {}
    additions, issues = [], []
    for rel, meta in sorted(files.items()):
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            _stage(snap, root, rel, "delete", files)
            continue
        if _sha_file(path) == meta["sha256"]:
            continue
        old, new = _text(os.path.join(snap, "files", rel)), _text(path)
        if meta["text"] and new is not None and _additive(old, new):
            additions.append(rel)
            continue
        _stage(snap, root, rel, "rewrite", files)
    reported, bad = _check_reported(conflicts_path, set(files))
    issues += bad
    for rel in _new_strays(root, files):
        issues.append(f"{rel}: new file under docs/ that is not a living doc. Write only "
                      "docs/architecture.md and docs/<domain>.md (with `doc:` front-matter); move "
                      "this content into the domain's doc and delete the file")
    record = {"reported": reported, "proposals": _load(os.path.join(snap, PROPOSALS), {}),
              "additions": additions}
    _dump(os.path.join(snap, CONFLICTS), record | {"report": report})
    count = len(reported) + len(record["proposals"])
    if report:
        if count or additions:
            _render(os.path.join(root, report), record)
        elif os.path.isfile(os.path.join(root, report)):
            os.remove(os.path.join(root, report))
    out = {"valid": not issues, "source_conflicts": count, "has_source_conflicts": count > 0,
           "source_additions": len(additions), "source_proposals": len(record["proposals"])}
    if issues:
        out["issues_summary"] = "\n".join(f"- {i}" for i in issues)
    return out


def review(snap):
    record = _load(os.path.join(snap, CONFLICTS), {}) or {}
    record.setdefault("reported", [])
    record.setdefault("proposals", {})
    count = len(record["reported"]) + len(record["proposals"])
    return {"has_source_conflicts": count > 0, "source_conflicts": count,
            "proposal_count": len(record["proposals"]),
            "summary": summary(record, record.get("report")) if count else "No conflicts."}


def apply(root, snap):
    manifest = (_load(os.path.join(snap, MANIFEST), {}) or {}).get("files") or {}
    proposals = _load(os.path.join(snap, PROPOSALS), {}) or {}
    applied, skipped = [], []
    for rel, p in sorted(proposals.items()):
        path = os.path.join(root, rel)
        was = (manifest.get(rel) or {}).get("sha256")
        now = _sha_file(path) if os.path.isfile(path) else None
        if now != was:
            skipped.append(f"{rel} (changed since the snapshot; not overwritten)")
            continue
        if p["kind"] == "delete":
            os.remove(path)
        else:
            shutil.copy2(os.path.join(snap, "proposed", rel), path)
        applied.append(rel)
    lines = [f"Applied to {len(applied)} source doc(s)" + (": " + ", ".join(applied) if applied else ".")]
    if skipped:
        lines.append("Skipped: " + "; ".join(skipped))
    return {"applied": len(applied), "skipped": len(skipped), "summary": " ".join(lines)}


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["list", "snapshot", "guard", "review", "apply"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--out")
    ap.add_argument("--snapshot")
    ap.add_argument("--conflicts")
    ap.add_argument("--report")
    a = ap.parse_args(argv[1:])
    root = os.path.abspath(a.root)
    snap = os.path.join(root, a.snapshot) if a.snapshot and not os.path.isabs(a.snapshot) else a.snapshot
    if a.cmd == "list":
        paths = source_paths(root)
        out = {"count": len(paths), "paths_csv": ",".join(paths)}
    elif a.cmd == "snapshot":
        if not a.out:
            ap.error("snapshot needs --out")
        out = snapshot(root, a.out if os.path.isabs(a.out) else os.path.join(root, a.out))
        out["snapshot"] = a.out
    else:
        if not snap:
            ap.error(f"{a.cmd} needs --snapshot")
        conflicts = a.conflicts and (a.conflicts if os.path.isabs(a.conflicts)
                                     else os.path.join(root, a.conflicts))
        out = (guard(root, snap, conflicts, a.report) if a.cmd == "guard"
               else review(snap) if a.cmd == "review" else apply(root, snap))
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
