#!/usr/bin/env python3
"""The feature's decision log: every PRD, HLD and LLD decision in one readable file, with the
decisions nobody confirmed first.

  decision_log.py sync [--root .] [--slug S] --md <decision-log.md>
                       --stage <NAME>=<record.json>[,<latest-queue.json>] [--stage ...]

Each stage's interview record (the file its interview node writes) is the only store of a
decision; this renders the records, in stage order, into one Markdown log and stores nothing
twice. When a stage's latest question queue lists `settled` points — ones the requirement,
design, code or docs already answer, recorded with their source instead of being asked — and no
interview ran to record them, `sync` adds them to that stage's record as `evidence` decisions.
A record that does not exist yet means the stage has not run.

With `--slug` the log opens with what a person should check first: assumptions (a
recommendation adopted without confirmation, by a person choosing "assume" or by autopilot),
decisions left open, and the gates the run mode answered on autopilot. The review pack and the
release gate read that section, so there is no separate assumption log.

The question validator (validate_prd_questions.py --log <the records' folder>) reads the same
records, so no stage asks a topic an earlier stage decided.

Prints one JSON line: {path, md_path, count, assumed, open, settled, summary, assumption_count,
open_count, autopilot_gate_count, unconfirmed_summary}. Always exits 0.

`--log <decision-log.json>` (workflows from before the records were the store) still writes that
JSON copy, with the Markdown beside it.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state as statemod  # noqa: E402

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
STAGE_ORDER = ("PRD", "HLD", "LLD")


def _full(root, rel):
    return rel if os.path.isabs(rel) else os.path.join(root, rel)


def _read(root, rel):
    try:
        with open(_full(root, rel), encoding="utf-8") as fh:
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
    for key in ("follow_up_of", "by", "evidence", "confirmed_at", "why"):
        if item.get(key):
            entry[key] = item[key]
    return entry


def record_settled(root, record_rel, queue_rel):
    """Add the queue's `settled` points the stage record does not hold yet to the record, so
    the record is the complete store whether or not an interview ran. -> ids added."""
    queue = _read(root, queue_rel) if queue_rel else None
    settled = [item for item in (queue or {}).get("settled") or []
               if isinstance(item, dict) and isinstance(item.get("topic"), str) and item["topic"]]
    if not settled:
        return []
    record = _read(root, record_rel) or {}
    decisions = [d for d in record.get("decisions") or [] if isinstance(d, dict)]
    topics = {d.get("topic") or d.get("id") for d in decisions}
    ids = {d.get("id") for d in decisions}
    now, added = statemod.now_iso(), []
    for item in settled:
        settled_id = f"settled-{item['topic']}"
        if item["topic"] in topics or settled_id in ids:
            continue
        decisions.append({
            "id": settled_id, "topic": item["topic"],
            "title": str(item.get("title") or "").strip(), "kind": "decision",
            "answer": str(item.get("decision") or "").strip(), "source": "evidence",
            "evidence": str(item.get("source") or "").strip(), "confirmed_at": now,
        })
        topics.add(item["topic"])
        added.append(settled_id)
    if not added:
        return []
    record = {"schema_version": 2, "rounds": [], **record, "updated_at": now,
              "decisions": decisions}
    full = _full(root, record_rel)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    tmp = f"{full}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, full)
    return added


def build(root, stages):
    """Every decision, in stage order, from the stage records (settled points recorded first)."""
    entries = []
    for spec in stages:
        name, _, files = spec.partition("=")
        record_rel, _, queue_rel = files.partition(",")
        record_settled(root, record_rel, queue_rel)
        for item in (_read(root, record_rel) or {}).get("decisions") or []:
            if isinstance(item, dict) and item.get("id"):
                entries.append(_entry(name, item))
    return entries


def _stage_of(filename):
    return os.path.splitext(filename)[0].replace("-context", "").upper()


def records_in(folder):
    """[(stage, path)] for the stage records in a decisions folder, in stage order."""
    try:
        names = [n for n in os.listdir(folder) if n.endswith(".json")
                 and n != "decision-log.json" and not n.startswith(".")]
    except OSError:
        return []
    found = []
    for name in names:
        doc = _read(folder, name)
        if doc is not None and isinstance(doc.get("decisions"), list):
            found.append((_stage_of(name), os.path.join(folder, name)))
    return sorted(found, key=lambda item: (STAGE_ORDER.index(item[0]) if item[0] in STAGE_ORDER
                                           else len(STAGE_ORDER), item[0]))


def entries_in(folder):
    """Every recorded decision of the feature, read straight from the stage records in `folder`
    — what validate_prd_questions.py --log and the interview server check a queue against."""
    entries = []
    for stage, path in records_in(folder):
        for item in (_read("", path) or {}).get("decisions") or []:
            if isinstance(item, dict) and item.get("id"):
                entries.append(_entry(stage, item))
    return entries


# ----------------------------------------------------------------- what nobody confirmed

def unconfirmed(entries, slug=None, root="."):
    """-> (run mode, assumptions, left open, gates answered on autopilot)."""
    assumed = [e for e in entries if e["source"] == "assumption"]
    left_open = [e for e in entries if e["source"] == "deferred"]
    state = (statemod.load(slug, root) if slug else None) or {}
    gates = [g for g in state.get("gates") or [] if isinstance(g, dict) and g.get("auto")]
    mode = (state.get("run") or {}).get("mode") or "human"
    return mode, assumed, left_open, gates


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def summarize_unconfirmed(assumed, left_open, gates):
    if not (assumed or left_open or gates):
        return "No assumptions, open items or autopilot decisions"
    return (f"{_plural(len(assumed), 'assumption')}, {len(left_open)} left open, "
            f"{_plural(len(gates), 'autopilot gate decision')}")


def summarize(entries):
    count = len(entries)
    assumed = sum(1 for e in entries if e["source"] == "assumption")
    left_open = sum(1 for e in entries if e["source"] == "deferred")
    settled = sum(1 for e in entries if e["source"] == "evidence")
    if not count:
        return "No decisions recorded yet"
    return (f"{count} decision(s): {settled} settled by evidence, {assumed} assumed, "
            f"{left_open} left open")


def render(entries, slug=None, mode=None, gates=()):
    assumed = [e for e in entries if e["source"] == "assumption"]
    left_open = [e for e in entries if e["source"] == "deferred"]
    lines = [f"# Decision log — {slug}" if slug else "# Decision log", ""]
    if mode:
        # deliver.py quotes this line in a pull request body
        lines += [f"Run mode: {mode}. {summarize_unconfirmed(assumed, left_open, gates)}.", ""]
    lines += [summarize(entries) + ".", ""]
    if assumed or left_open or gates:
        lines += ["## Not confirmed by a person", "",
                  "Check these first: nobody confirmed them.", ""]

        def section(title, items):
            lines.extend([f"### {title}", ""])
            if not items:
                lines.extend(["None.", ""])
                return
            for item in items:
                who = "autopilot" if item.get("by") == "autopilot" else "chosen at the interview"
                lines.append(f"- **{item['stage']} · {item['title'] or item['topic']}** ({who}): "
                             f"{item['answer']}")
                if item.get("why"):
                    lines.append(f"  Why it matters: {item['why']}")
            lines.append("")

        section("Assumptions", assumed)
        section("Left open", left_open)
        lines.extend(["### Gates answered on autopilot", ""])
        if gates:
            lines.extend(f"- {g['step']} → {g['option']} ({g['auto']} mode, {g.get('at', '')})"
                         for g in gates)
        else:
            lines.append("None.")
        lines.append("")
    elif mode:
        lines += ["Every decision in this feature was confirmed by a person or settled by "
                  "evidence.", ""]
    stage = None
    for entry in entries:
        if entry["stage"] != stage:
            if stage is not None:
                lines.append("")
            stage = entry["stage"]
            lines += [f"## {stage}", ""]
        label = LABELS.get(entry["source"], entry["source"])
        if entry.get("by") == "autopilot":
            label += " (autopilot)"
        tail = f" — source: `{entry['evidence']}`" if entry.get("evidence") else ""
        follow = f" (follow-up of {entry['follow_up_of']})" if entry.get("follow_up_of") else ""
        lines.append(f"- **{entry['title'] or entry['topic']}**{follow} [{label}]: "
                     f"{entry['answer']}{tail}")
    return "\n".join(lines).rstrip("\n") + "\n"


def write_log(root, md_rel, stages, slug=None, json_rel=None):
    """Render the log to `md_rel`; -> the result fields `sync` prints."""
    entries = build(root, stages)
    mode, assumed, left_open, gates = unconfirmed(entries, slug, root)
    md = _full(root, md_rel)
    os.makedirs(os.path.dirname(md) or ".", exist_ok=True)
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(render(entries, slug, mode if slug else None, gates))
    result = {"md_path": os.path.relpath(md, root)}
    if json_rel:
        full = _full(root, json_rel)
        with open(full, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "entries": [
                {k: v for k, v in e.items() if k != "why"} for e in entries]}, fh, indent=2,
                ensure_ascii=False)
            fh.write("\n")
        result["path"] = os.path.relpath(full, root)
    else:
        result["path"] = result["md_path"]
    result.update({
        "count": len(entries),
        "assumed": len(assumed),
        "open": len(left_open),
        "settled": sum(1 for e in entries if e["source"] == "evidence"),
        "summary": summarize(entries),
        "assumption_count": len(assumed),
        "open_count": len(left_open),
        "autopilot_gate_count": len(gates),
        "unconfirmed_summary": summarize_unconfirmed(assumed, left_open, gates),
    })
    return result


def sync_run(slug, root="."):
    """Render the shipped layout's log for a run from whatever stage records it has (used when
    a run is migrated; workflows call `sync` with their own paths)."""
    import run_layout

    def rel(path):  # write_log takes paths relative to the workspace root, like a workflow's
        return os.path.relpath(path, root)

    folder = run_layout.path(slug, root, run_layout.DECISIONS_DIR)
    stages = []
    for stage, record in records_in(folder):
        queue = run_layout.path(slug, root, run_layout.queue(stage))
        stages.append(f"{stage}={rel(record)},{rel(queue)}")
    if not stages:
        return None
    return write_log(root, rel(run_layout.path(slug, root, run_layout.DECISION_LOG)), stages, slug)


def cmd_sync(args):
    if not args.md and not args.log:
        print("decision_log.py sync needs --md <decision-log.md>", file=sys.stderr)
        return 2
    md = args.md or os.path.splitext(args.log)[0] + ".md"
    print(json.dumps(write_log(args.root, md, args.stage, args.slug, args.log)))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", help="the run: adds its mode and the gates answered on autopilot")
    p.add_argument("--md", help="where to write the readable log")
    p.add_argument("--log", help="(earlier workflows) also write this JSON copy of the log")
    p.add_argument("--stage", action="append", default=[])
    p.set_defaults(fn=cmd_sync)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
