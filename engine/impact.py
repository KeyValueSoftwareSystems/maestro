#!/usr/bin/env python3
"""The feature's impact assessment: which repositories it changes, checked by the engine.

An agent reads the approved PRD and the codebase maps and writes impact.json:
  {"schema_version": 1,
   "repos": [{"name": "backend", "change": "what changes there, in one line"}],
   "interfaces_change": true,     # a call or event between repositories is added or changed
   "data_migration": false,       # stored data changes shape
   "infrastructure_change": false,
   "size": "minor",              # minor | major: a small self-contained change takes the light design path
   "summary": "one line",
   # schema_version 2 adds what the feature touches, each item with a reason and its evidence:
   "domains": [{"name": "payments", "reason": "...", "evidence": "docs/functional/payments.md"}],
   "tables": [...], "jobs": [...], "queues": [...],       # same item shape
   "endpoints": [{"name": "POST /v1/fee-groups", "reason": "...", "evidence": "...",
                  "consumers": ["web: FeeGroupsScreen"]}],  # consumers also allowed on queues
   "rules": [{"id": "PL-INV-001", ...}], "scenarios": [{"id": "PL-CS-001", ...}]}
Every repository must be one the workspace has (codebase/* or the root itself). Sizing takes the
light path for `minor` and the full path for `major`, and the LLD scope defaults to these repositories.
Rules and scenarios must be defined in the living docs (living_docs.py), domains must have a page.

  impact.py validate --root . --impact <impact.json> [--prd <prd.md>]
Prints one JSON line {valid, repos_csv, count, interfaces_change, data_migration,
infrastructure_change, item_count, scenarios_csv, issues_summary, summary}; always exits 0.
With --prd, a change scenario (docs/impact/side-effects.yaml) whose `when_changing` names something
the PRD or the assessment's evidence mentions is added with its rules and `also_impacts` items, so a
rule-driven match never depends on the agent remembering it (match_scenarios / merge).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import living_docs  # noqa: E402

FLAGS = ("interfaces_change", "data_migration", "infrastructure_change")
SIZES = ("minor", "major")
# kind -> the key naming an item; rules and scenarios are ids, everything else a name
KINDS = (("domains", "name"), ("tables", "name"), ("jobs", "name"), ("queues", "name"),
         ("endpoints", "name"), ("rules", "id"), ("scenarios", "id"))
# side-effects also_impacts lists that become impact items
ALSO = ("domains", "tables", "queues", "endpoints")
ID_RE = {k: re.compile(rf"^{living_docs.PREFIX_RE}-{k}-\d{{3}}$") for k in ("INV", "CS")}


def _items(doc, kind, issues):
    """Validated items of one kind: [{key, reason, evidence, consumers?, source?}]."""
    key = dict(KINDS)[kind]
    raw = doc.get(kind)
    if raw is None:
        return []
    if not isinstance(raw, list):
        issues.append(f"{kind} must be a list")
        return []
    out = []
    for index, item in enumerate(raw, 1):
        where = f"{kind}[{index}]"
        if not isinstance(item, dict) or not str(item.get(key) or "").strip():
            issues.append(f"{where}.{key} is required")
            continue
        for field in ("reason", "evidence"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                issues.append(f"{where} ({item[key]}): {field} is required, one line")
        consumers = item.get("consumers")
        if consumers is not None and not (isinstance(consumers, list)
                                          and all(isinstance(c, str) for c in consumers)):
            issues.append(f"{where} ({item[key]}): consumers must be a list of names")
        out.append(dict(item, **{key: str(item[key]).strip()}))
    return out


def _check_docs(root, lists, issues):
    """Rule, scenario and domain names the impact cites must exist in the living docs, when any do."""
    docs = living_docs.load_docs(root)
    defs = living_docs.collect_ids(docs, living_docs.Report())
    scenarios = living_docs.load_side_effects(root, living_docs.Report()) or []
    domains = {d.domain for d in docs if d.domain}
    rules = {i for i in defs if "-INV-" in i}
    known_cs = {i for i in defs if "-CS-" in i} | {
        str(sc.get("id")) for sc in scenarios if isinstance(sc, dict)}
    for kind, label, ids in (("rules", "INV", rules), ("scenarios", "CS", known_cs)):
        for item in lists[kind]:
            if not ID_RE[label].match(item["id"]):
                issues.append(f"{kind}: {item['id']!r} is not a <PREFIX>-{label}-NNN id")
            elif (docs or scenarios) and item["id"] not in ids:
                issues.append(f"{kind}: {item['id']} is not defined in the living docs")
    if domains:
        for item in lists["domains"]:
            if item["name"] not in domains:
                issues.append(f"domains: {item['name']!r} has no docs/functional or docs/technical page")


def match_scenarios(root, texts):
    """Side-effects scenarios whose when_changing names a file or symbol found in any of texts."""
    text = "\n".join(t for t in texts if t)
    found = []
    for sc in living_docs.load_side_effects(root, living_docs.Report()) or []:
        if not isinstance(sc, dict) or not sc.get("id"):
            continue
        for entry in sc.get("when_changing") or []:
            thing = str(entry).strip()
            head, _, tail = thing.partition(":")
            if tail and "/" not in head and " " not in head:
                thing = tail.strip()  # "repo:path" -> path
            if not thing:
                continue
            # shortcut: substring/word match, no code parsing — upgrade if false hits show up
            if "/" in thing or os.path.splitext(thing)[1].lower() in living_docs.SOURCE_EXT:
                hit = thing in text or os.path.basename(thing) in text
            else:
                hit = re.search(r"(?<![A-Za-z0-9_])" + re.escape(thing) + r"(?![A-Za-z0-9_])", text)
            if hit:
                found.append(sc)
                break
    return found


def merge(doc, scenarios):
    """Add each matched scenario, its rules and its also_impacts items to doc. -> ids newly added."""
    added = []
    for sc in scenarios:
        cs = str(sc["id"])
        why = f"scenario {cs}: {sc.get('summary') or 'change scenario'}"
        evidence = f"docs/impact/side-effects.yaml#{cs}"
        wanted = [("scenarios", "id", cs)] + [("rules", "id", str(r)) for r in sc.get("rules") or []]
        also = sc.get("also_impacts") if isinstance(sc.get("also_impacts"), dict) else {}
        wanted += [(kind, "name", str(n)) for kind in ALSO for n in also.get(kind) or []]
        for kind, key, name in wanted:
            items = doc.setdefault(kind, [])
            if any(isinstance(i, dict) and str(i.get(key, "")).strip() == name for i in items):
                continue
            items.append({key: name, "reason": why, "evidence": evidence, "source": "engine"})
            if kind == "scenarios":
                added.append(cs)
    if added:
        doc["schema_version"] = max(2, int(doc.get("schema_version") or 1))
    return added


def load(root, path):
    """-> (impact, issues). impact is None when the file is unusable."""
    full = path if os.path.isabs(path) else os.path.join(root, path)
    try:
        with open(full, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None, [f"{path} is missing"]
    except (OSError, ValueError) as exc:
        return None, [f"{path} is not readable JSON: {exc}"]
    if not isinstance(doc, dict):
        return None, ["the impact assessment must be a JSON object"]
    issues = []
    discovered = {name.lower(): name for name, _path in codebase_scan.discover_repos(root)}
    repos = []
    items = doc.get("repos")
    if not isinstance(items, list) or not items:
        issues.append("repos must list at least one repository the feature changes")
        items = []
    for index, item in enumerate(items, 1):
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip():
            issues.append(f"repos[{index}].name is required")
        elif name.strip().lower() not in discovered:
            issues.append(f"repos[{index}]: {name!r} is not a repository in this workspace "
                          f"({', '.join(sorted(discovered.values())) or 'none found'})")
        elif not isinstance(item.get("change"), str) or not item["change"].strip():
            issues.append(f"repos[{index}].change must say what changes in {name}")
        else:
            canonical = discovered[name.strip().lower()]
            if canonical not in repos:
                repos.append(canonical)
    for flag in FLAGS:
        if not isinstance(doc.get(flag), bool):
            issues.append(f"{flag} must be true or false")
    size = str(doc.get("size") or "").strip().lower()
    if size not in SIZES:
        issues.append("size must be minor or major")
    if doc.get("schema_version", 1) not in (1, 2):
        issues.append("schema_version must be 1 or 2")
    lists = {kind: _items(doc, kind, issues) for kind, _key in KINDS}
    _check_docs(root, lists, issues)
    if issues:
        return None, issues
    return {"repos": repos, "size": size, **{flag: doc[flag] for flag in FLAGS},
            "summary": str(doc.get("summary") or "").strip(), **lists}, []


def _merge_from_prd(root, path, prd):
    """Engine-matched scenarios from the PRD and the assessment's evidence, written into impact.json."""
    full = path if os.path.isabs(path) else os.path.join(root, path)
    try:
        with open(full, encoding="utf-8") as fh:
            doc = json.load(fh)
        with open(prd if os.path.isabs(prd) else os.path.join(root, prd), encoding="utf-8") as fh:
            prd_text = fh.read()
    except (OSError, ValueError):
        return []
    evidence = [str(i.get("evidence", "")) for kind, _k in KINDS for i in doc.get(kind) or []
                if isinstance(i, dict)] + [str(r.get("change", "")) for r in doc.get("repos") or []
                                           if isinstance(r, dict)]
    added = merge(doc, match_scenarios(root, [prd_text] + evidence))
    if added:
        with open(full, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
    return added


def validate(root, path, prd=None):
    impact, issues = load(root, path)
    added = []
    if impact is not None and prd:
        added = _merge_from_prd(root, path, prd)
        if added:
            impact, issues = load(root, path)
    if impact is None:
        return {"valid": False, "repos_csv": "", "count": 0, "size": "",
                **{flag: False for flag in FLAGS}, "item_count": 0, "scenarios_csv": "",
                "issues_summary": " | ".join(issues[:8]),
                "summary": "Impact assessment is not valid"}
    changes = [label for flag, label in (("interfaces_change", "interfaces between repositories"),
                                          ("data_migration", "a data migration"),
                                          ("infrastructure_change", "infrastructure"))
               if impact[flag]]
    summary = (f"{impact['size'].capitalize()} change to {len(impact['repos'])} repositor{'y' if len(impact['repos']) == 1 else 'ies'}"
               f" ({', '.join(impact['repos'])})"
               + (f"; also {', '.join(changes)}" if changes else ""))
    count = sum(len(impact[kind]) for kind, _k in KINDS)
    scenarios = [i["id"] for i in impact["scenarios"]]
    if count:
        summary += f"; {count} impacted items"
    if added:
        summary += f" (engine added scenario{'s' if len(added) > 1 else ''} {', '.join(added)})"
    return {"valid": True, "repos_csv": ",".join(impact["repos"]), "count": len(impact["repos"]),
            "size": impact["size"], **{flag: impact[flag] for flag in FLAGS},
            "item_count": count, "scenarios_csv": ",".join(scenarios),
            "issues_summary": "Impact assessment is valid", "summary": summary}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--root", default=".")
    p.add_argument("--impact", required=True)
    p.add_argument("--prd", default="", help="match change scenarios against the PRD and merge them")
    args = parser.parse_args(argv)
    print(json.dumps(validate(args.root, args.impact, args.prd or None)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
