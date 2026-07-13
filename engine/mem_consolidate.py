#!/usr/bin/env python3
"""Deterministic memory consolidation — the engine-owned 'reduce' step.

This is workflow-critical FUNCTIONALITY, so it lives in the engine (stdlib, tested), not in
a swappable skill: folding per-run observation drops into the candidate ledger, counting
DISTINCT source runs, promoting corroborated lessons past the threshold, pruning/capping, and
rendering the injected knowledge/*.md. Skills only PRODUCE the structured incoming/*.json
(their LLM judgement about what the lessons are); swapping a skill cannot change how
corroboration or promotion works, because none of that lives in the skill.

Invoked as a workflow `script` node:  python3 engine/mem_consolidate.py .maestro/memory

Store layout under <memory_dir> (default .maestro/memory):
  incoming/<slug>.json      {"slug": "...", "lessons": [{"domain","key","text","authoritative"?}]}
                            written by the retrospect / build-knowledge skills; consumed + cleared here
  candidates/<domain>.json  engine-owned ledger: [{"key","text","slugs":[...],"authoritative":bool}]
  knowledge/<domain>.md     engine-RENDERED injected output (authoritative OR seen in >= threshold runs)
  index.md                  one line per rendered knowledge file

Promotion threshold: --threshold N, else memory.promote_threshold from ./maestro.config.yaml,
else 3. Prints one JSON line: {"promoted": <int>, "candidates": <int>, "domains": <int>}.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import wf
except ImportError:  # imported as a package (tests)
    from . import wf

DEFAULT_THRESHOLD = 3
MAX_PER_DOMAIN = 40  # size cap so injected knowledge stays cheap


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _config_threshold(root="."):
    path = os.path.join(root, "maestro.config.yaml")
    if not os.path.exists(path):
        return None
    try:
        doc = wf.load_file(path) or {}
        val = (doc.get("memory") or {}).get("promote_threshold")
        return int(val) if val is not None else None
    except (OSError, ValueError, TypeError):
        return None


def consolidate(memory_dir, threshold):
    """Fold incoming drops into the ledger, promote, render, and clear. Returns a summary."""
    incoming_dir = os.path.join(memory_dir, "incoming")
    candidates_dir = os.path.join(memory_dir, "candidates")
    knowledge_dir = os.path.join(memory_dir, "knowledge")

    # 1. load the existing candidate ledger: domain -> {key: entry}
    ledger = {}
    if os.path.isdir(candidates_dir):
        for name in sorted(os.listdir(candidates_dir)):
            if not name.endswith(".json"):
                continue
            doc = _load_json(os.path.join(candidates_dir, name)) or []
            entries = {}
            for e in doc if isinstance(doc, list) else []:
                if isinstance(e, dict) and e.get("key"):
                    entries[e["key"]] = {
                        "text": str(e.get("text", "")),
                        "slugs": list(dict.fromkeys(e.get("slugs") or [])),
                        "authoritative": bool(e.get("authoritative")),
                    }
            ledger[name[:-5]] = entries

    # 2. fold incoming drops (distinct-slug counting; unparseable drops skipped)
    folded = []
    if os.path.isdir(incoming_dir):
        for name in sorted(os.listdir(incoming_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(incoming_dir, name)
            doc = _load_json(path)
            if not isinstance(doc, dict):
                continue  # skip non-object / unparseable drops (e.g. test stubs)
            slug = str(doc.get("slug") or name[:-5])
            for lesson in doc.get("lessons") or []:
                if not isinstance(lesson, dict):
                    continue
                domain, key, text = lesson.get("domain"), lesson.get("key"), lesson.get("text")
                if not (domain and key and text):
                    continue
                entry = ledger.setdefault(domain, {}).setdefault(
                    key, {"text": "", "slugs": [], "authoritative": False})
                entry["text"] = str(text)
                if lesson.get("authoritative"):
                    entry["authoritative"] = True
                if slug not in entry["slugs"]:
                    entry["slugs"].append(slug)
            folded.append(path)

    # 3. persist the ledger, render knowledge, count
    os.makedirs(candidates_dir, exist_ok=True)
    os.makedirs(knowledge_dir, exist_ok=True)
    promoted_total = staged_total = 0
    index_lines = ["# memory index", ""]
    for domain in sorted(ledger):
        entries = ledger[domain]
        with open(os.path.join(candidates_dir, domain + ".json"), "w", encoding="utf-8") as fh:
            json.dump([{"key": k, **v} for k, v in sorted(entries.items())],
                      fh, indent=2, sort_keys=True)
        promoted = []
        for key, e in entries.items():
            if e["authoritative"] or len(e["slugs"]) >= threshold:
                promoted.append((key, e))
            else:
                staged_total += 1
        # size cap: keep the best-corroborated first
        promoted.sort(key=lambda ke: (ke[1]["authoritative"], len(ke[1]["slugs"])), reverse=True)
        promoted = promoted[:MAX_PER_DOMAIN]
        kpath = os.path.join(knowledge_dir, domain + ".md")
        if promoted:
            lines = [f"# {domain} — prior lessons", ""]
            for _key, e in promoted:
                prov = "authoritative" if e["authoritative"] else (
                    f"seen: {len(e['slugs'])} — {', '.join(e['slugs'])}")
                lines.append(f"- {e['text']} _({prov})_")
            with open(kpath, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            promoted_total += len(promoted)
            index_lines.append(f"- knowledge/{domain}.md — {len(promoted)} lesson(s)")
        elif os.path.exists(kpath):
            os.remove(kpath)  # nothing qualifies any more

    with open(os.path.join(memory_dir, "index.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(index_lines) + "\n")

    # 4. clear the incoming drops we folded (leave any we skipped)
    for path in folded:
        try:
            os.remove(path)
        except OSError:
            pass

    return {"promoted": promoted_total, "candidates": staged_total, "domains": len(ledger)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Consolidate the Maestro memory store.")
    ap.add_argument("memory_dir", help="path to the memory store (e.g. .maestro/memory)")
    ap.add_argument("--threshold", type=int, default=None,
                    help="distinct-run corroboration threshold (default: config or 3)")
    ap.add_argument("--root", default=".", help="repo root for maestro.config.yaml lookup")
    args = ap.parse_args(argv)
    threshold = args.threshold
    if threshold is None:
        threshold = _config_threshold(args.root)
    if threshold is None:
        threshold = DEFAULT_THRESHOLD
    result = consolidate(args.memory_dir, threshold)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
