#!/usr/bin/env python3
"""The feature's decision log: every PRD, HLD and LLD decision in one place.

  decision_log.py sync [--root .] --log <decision-log.json>
                       --stage <NAME>=<decisions.json>[,<latest-queue.json>] [--stage ...]

Rebuilds the log from each stage's cumulative interview decisions (interview nodes write them) and,
when given, that stage's latest question queue's `settled` points — the ones the requirement,
design, code or docs already answer, recorded with their source instead of being asked. Stages are
listed in order; a missing file means that stage has not run yet.

The question validator (validate_prd_questions.py --log) reads the log so no stage asks a topic an
earlier stage decided. Writes the JSON log and a readable `<log>.md` beside it, and prints one
JSON line: {path, md_path, count, assumed, open, settled, summary}. Always exits 0.
"""
import argparse
import json
import os
import sys

LABELS = {
    "accepted-proposal": "recommendation accepted",
    "chosen-alternative": "alternative chosen",
    "user-answer": "answered",
    "user-raised": "raised by the human",
    "assumption": "ASSUMED — unconfirmed",
    "deferred": "OPEN — deferred",
    "evidence": "settled by evidence",
    "legacy-confirmed": "confirmed",
}


def _read(root, rel):
    full = rel if os.path.isabs(rel) else os.path.join(root, rel)
    try:
        with open(full, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _entry(stage, item):
    entry = {
        "stage": stage,
        "id": item.get("id"),
        "topic": item.get("topic") or item.get("id"),
        "title": str(item.get("title") or "").strip(),
        "answer": str(item.get("answer") or "").strip(),
        "source": item.get("source") or "user-answer",
    }
    for key in ("follow_up_of", "by", "evidence", "confirmed_at"):
        if item.get(key):
            entry[key] = item[key]
    return entry


def build(root, stages):
    entries, seen = [], set()
    for spec in stages:
        name, _, files = spec.partition("=")
        decisions_rel, _, queue_rel = files.partition(",")
        decisions = _read(root, decisions_rel) or {}
        for item in decisions.get("decisions") or []:
            if isinstance(item, dict) and item.get("id"):
                entry = _entry(name, item)
                entries.append(entry)
                seen.add((name, entry["topic"]))
        queue = _read(root, queue_rel) if queue_rel else None
        for item in (queue or {}).get("settled") or []:
            if not isinstance(item, dict) or not item.get("topic"):
                continue
            if (name, item["topic"]) in seen:
                continue
            entries.append(_entry(name, {
                "id": f"settled-{item['topic']}", "topic": item["topic"],
                "title": item.get("title"), "answer": item.get("decision"),
                "source": "evidence", "evidence": item.get("source"),
            }))
            seen.add((name, item["topic"]))
    return entries


def summarize(entries):
    count = len(entries)
    assumed = sum(1 for e in entries if e["source"] == "assumption")
    left_open = sum(1 for e in entries if e["source"] == "deferred")
    settled = sum(1 for e in entries if e["source"] == "evidence")
    if not count:
        return "No decisions recorded yet"
    return (f"{count} decision(s): {settled} settled by evidence, {assumed} assumed, "
            f"{left_open} left open")


def render(entries):
    lines = ["# Decision log", "", summarize(entries) + ".", ""]
    stage = None
    for entry in entries:
        if entry["stage"] != stage:
            stage = entry["stage"]
            lines += [f"## {stage}", ""]
        label = LABELS.get(entry["source"], entry["source"])
        if entry.get("by") == "autopilot":
            label += " (autopilot)"
        tail = f" — source: `{entry['evidence']}`" if entry.get("evidence") else ""
        follow = f" (follow-up of {entry['follow_up_of']})" if entry.get("follow_up_of") else ""
        lines.append(f"- **{entry['title'] or entry['topic']}**{follow} [{label}]: "
                     f"{entry['answer']}{tail}")
    return "\n".join(lines) + "\n"


def cmd_sync(args):
    entries = build(args.root, args.stage)
    full = args.log if os.path.isabs(args.log) else os.path.join(args.root, args.log)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": 1, "entries": entries}, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    md = os.path.splitext(full)[0] + ".md"
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(render(entries))
    print(json.dumps({
        "path": os.path.relpath(full, args.root),
        "md_path": os.path.relpath(md, args.root),
        "count": len(entries),
        "assumed": sum(1 for e in entries if e["source"] == "assumption"),
        "open": sum(1 for e in entries if e["source"] == "deferred"),
        "settled": sum(1 for e in entries if e["source"] == "evidence"),
        "summary": summarize(entries),
    }))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync")
    p.add_argument("--root", default=".")
    p.add_argument("--log", required=True)
    p.add_argument("--stage", action="append", default=[])
    p.set_defaults(fn=cmd_sync)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
