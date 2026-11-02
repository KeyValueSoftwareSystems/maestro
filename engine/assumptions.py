#!/usr/bin/env python3
"""The feature's assumption log: every decision nobody confirmed, in one short file.

Collects, from the interview decision files and the run ledger:
  - assumptions: a recommendation adopted without confirmation — by a person choosing "assume"
    at an interview, or by autopilot in `auto` mode;
  - items left open: deferred decisions, including questions autopilot had no recommendation for;
  - gates the run mode answered on autopilot.

Writes `.maestro/runs/<slug>/assumptions.md` (or --out) and prints one JSON line:
{path, assumption_count, open_count, autopilot_gate_count, summary}. The review pack shows it
first, so a person checks the guesses before anything else.

  assumptions.py render [--root .] --slug S --decisions <context.json> [--decisions ...] [--out P]

A decisions file that does not exist yet is skipped (the stage never asked anything).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state as statemod  # noqa: E402


def _stage(path):
    name = os.path.basename(path)
    for suffix in ("-context.json", ".json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.upper() if len(name) <= 4 else name.replace("-", " ").capitalize()


def _decisions(root, rel):
    full = rel if os.path.isabs(rel) else os.path.join(root, rel)
    try:
        with open(full, encoding="utf-8") as fh:
            document = json.load(fh)
    except (OSError, ValueError):
        return []
    items = document.get("decisions") if isinstance(document, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


def collect(root, slug, decision_files):
    assumed, left_open = [], []
    for rel in decision_files:
        stage = _stage(rel)
        for item in _decisions(root, rel):
            entry = {
                "stage": stage,
                "title": str(item.get("title") or item.get("id") or "").strip(),
                "answer": str(item.get("answer") or "").strip(),
                "why": str(item.get("why") or "").strip(),
                "by": item.get("by") or "person",
            }
            if item.get("source") == "assumption":
                assumed.append(entry)
            elif item.get("source") == "deferred":
                left_open.append(entry)
    state = statemod.load(slug, root) or {}
    gates = [g for g in state.get("gates") or [] if isinstance(g, dict) and g.get("auto")]
    mode = (state.get("run") or {}).get("mode") or "human"
    return mode, assumed, left_open, gates


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def summarize(assumed, left_open, gates):
    if not (assumed or left_open or gates):
        return "No assumptions, open items or autopilot decisions"
    return (f"{_plural(len(assumed), 'assumption')}, {len(left_open)} left open, "
            f"{_plural(len(gates), 'autopilot gate decision')}")


def render(slug, mode, assumed, left_open, gates):
    lines = [f"# Assumptions — {slug}", "",
             f"Run mode: {mode}. {summarize(assumed, left_open, gates)}.", ""]
    if not (assumed or left_open or gates):
        lines.append("Every decision in this feature was confirmed by a person.")
        return "\n".join(lines) + "\n"
    lines += ["Check these first: nobody confirmed them.", ""]

    def section(title, items, note):
        lines.extend([f"## {title}", ""])
        if not items:
            lines.extend(["None.", ""])
            return
        for item in items:
            who = "autopilot" if item["by"] == "autopilot" else "chosen at the interview"
            lines.append(f"- **{item['stage']} · {item['title']}** ({who}): {item['answer']}")
            if item["why"]:
                lines.append(f"  {note}: {item['why']}")
        lines.append("")

    section("Assumptions", assumed, "Why it matters")
    section("Left open", left_open, "Why it matters")
    lines.extend(["## Gates answered on autopilot", ""])
    if gates:
        lines.extend(f"- {g['step']} → {g['option']} ({g['auto']} mode, {g.get('at', '')})"
                     for g in gates)
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def cmd_render(args):
    mode, assumed, left_open, gates = collect(args.root, args.slug, args.decisions)
    out = args.out or os.path.join(statemod.feature_dir(args.slug, args.root), "assumptions.md")
    full = out if os.path.isabs(out) else os.path.join(args.root, out)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(render(args.slug, mode, assumed, left_open, gates))
    print(json.dumps({
        "path": os.path.relpath(full, args.root),
        "assumption_count": len(assumed),
        "open_count": len(left_open),
        "autopilot_gate_count": len(gates),
        "summary": summarize(assumed, left_open, gates),
    }))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("render")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--decisions", action="append", default=[])
    p.add_argument("--out")
    p.set_defaults(fn=cmd_render)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
