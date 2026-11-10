#!/usr/bin/env python3
"""Impact trace: every item the impact assessment lists is dealt with in the design documents.

  impact_trace.py check --root . --impact impact.json --docs a.md[,b.md] --stage hld|lld
                        [--match] [--out impact-trace.md]

An item (a domain, table, job, queue, endpoint, INV rule or CS scenario from impact.json schema 2) is
covered when a document names it (whole token, any case; an endpoint by its path). A line that names
an item and says "no change needed" must also say why ("because …"). --match first adds the change
scenarios the documents' planned files or symbols trigger (impact.match_scenarios), so a scenario
the design itself sets off must be covered too. --out writes the impact report: each item, its
reason, evidence, consumers and where the design covers it.

Prints one JSON line {valid, item_count, missing_csv, issues_summary, report_path}; always exits 0
(the workflow routes on `valid`). No usable assessment (greenfield, skipped, no items) is valid.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import impact  # noqa: E402

KIND_LABEL = {"domains": "domain", "tables": "table", "jobs": "job", "queues": "queue",
              "endpoints": "endpoint", "rules": "rule", "scenarios": "scenario"}
STAGE_LABEL = {"hld": "the HLD", "lld": "the LLDs"}


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _needle(kind, name):
    """The text a document must contain: an endpoint's path, else the name itself."""
    if kind == "endpoints":
        m = re.match(r"^[A-Za-z]+\s+(\S+)$", name)
        if m:
            return m.group(1)
    return name


def _pattern(needle):
    return re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(needle) + r"(?![A-Za-z0-9_])", re.I)


def trace(root, impact_path, docs, stage, match=False):
    full = impact_path if os.path.isabs(impact_path) else os.path.join(root, impact_path)
    texts = {}
    for path in docs:
        text = _read(path if os.path.isabs(path) else os.path.join(root, path))
        if text is not None:
            texts[path] = text
    added = []
    if match and os.path.isfile(full):
        try:
            with open(full, encoding="utf-8") as fh:
                doc = json.load(fh)
            added = impact.merge(doc, impact.match_scenarios(root, texts.values()))
            if added:
                with open(full, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, indent=2)
                    fh.write("\n")
        except (OSError, ValueError):
            pass
    assessed, _issues = impact.load(root, impact_path)
    rows, missing, issues = [], [], []
    if assessed is None:
        return rows, missing, ["no valid impact assessment: nothing to trace"], added, True
    where = STAGE_LABEL.get(stage, "the design")
    if not texts:
        issues.append(f"none of the design documents exist: {', '.join(docs)}")
    for kind, key in impact.KINDS:
        for item in assessed[kind]:
            name = item[key]
            pat = _pattern(_needle(kind, name))
            hits = [path for path, text in texts.items() if pat.search(text)]
            for path in hits:
                for line in texts[path].splitlines():
                    if pat.search(line) and "no change needed" in line.lower() \
                            and not re.search(r"\bbecause\b\s*\S", line, re.I):
                        issues.append(f"{os.path.basename(path)} says {name} needs no change but not "
                                      f"why: write \"{name}: no change needed, because …\"")
            rows.append((kind, item, hits))
            if not hits:
                missing.append(name)
                issues.append(f"{where} does not deal with {KIND_LABEL[kind]} {name} "
                              f"(reason: {item.get('reason', '')}). Cover it, or write "
                              f"\"{name}: no change needed, because …\"")
    return rows, missing, issues, added, False


def report(rows, stage, added):
    lines = [f"# Impact report ({stage.upper()})", "",
             "Everything the impact assessment says this feature touches, and where the design deals "
             "with it. Read this before the design.", ""]
    if added:
        lines += [f"Change scenarios added by the engine: {', '.join(added)}", ""]
    lines += ["| Kind | Item | Why | Evidence | Consumers | Covered in |",
              "|------|------|-----|----------|-----------|------------|"]
    for kind, item, hits in rows:
        name = item.get("name") or item.get("id")
        cells = [KIND_LABEL[kind], f"`{name}`", item.get("reason", ""), item.get("evidence", ""),
                 ", ".join(item.get("consumers") or []),
                 ", ".join(os.path.basename(h) for h in hits) or "**MISSING**"]
        lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
    if not rows:
        lines.append("| — | no impacted items listed | | | | |")
    return "\n".join(lines) + "\n"


def cmd_check(args):
    docs = [d.strip() for d in args.docs.split(",") if d.strip()]
    rows, missing, issues, added, skipped = trace(args.root, args.impact, docs, args.stage, args.match)
    report_path = ""
    if args.out:
        report_path = args.out
        full = args.out if os.path.isabs(args.out) else os.path.join(args.root, args.out)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(report(rows, args.stage, added))
    valid = skipped or not issues
    summary = (issues[0] if skipped else " | ".join(issues[:8]) if issues
               else f"All {len(rows)} impacted items are dealt with in {STAGE_LABEL.get(args.stage, 'the design')}")
    print(json.dumps({"valid": valid, "item_count": len(rows), "missing_csv": ",".join(missing),
                      "added_scenarios_csv": ",".join(added), "issues_summary": summary,
                      "report_path": report_path}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("--root", default=".")
    p.add_argument("--impact", required=True)
    p.add_argument("--docs", required=True, help="comma-separated design documents")
    p.add_argument("--stage", choices=("hld", "lld"), default="hld")
    p.add_argument("--match", action="store_true",
                   help="first add the change scenarios the documents trigger")
    p.add_argument("--out", default="")
    args = parser.parse_args(argv)
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
