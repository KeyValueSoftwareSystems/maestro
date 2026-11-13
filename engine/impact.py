#!/usr/bin/env python3
"""The feature's impact assessment: which repositories it changes, checked by the engine.

An agent reads the approved PRD and the codebase maps and writes impact.json. It records facts,
never a verdict: the engine (sizing.py) decides the design path from them.
  {"schema_version": 3,
   "repos": [{"name": "backend", "change": "what changes there, in one line"}],
   "interface_change": "lockstep", # none | lockstep (repos change together, wire format unchanged)
                                   # | shape (an endpoint, event, field or enum member added/changed/removed)
   "data_change": "none",          # none | additive (optional column/field) | reshape (new entity,
                                   # type change, backfill)
   "infrastructure_change": false,
   "compatibility_risk": true,     # deployed clients or old app versions break if shipped out of order
   "open_decisions": [{"question": "...", "kind": "rollout", "evidence": "..."}],
                                   # kind: placement | integration | data-model | interface | quality
                                   # (an architecture document answers these) | rollout | detail
   "summary": "one line",
   # what the feature touches, each item with a reason and its evidence:
   "domains": [{"name": "payments", "reason": "...", "evidence": "docs/functional/payments.md"}],
   "tables": [...], "jobs": [...], "queues": [...],       # same item shape
   "endpoints": [{"name": "POST /v1/fee-groups", "reason": "...", "evidence": "...",
                  "consumers": ["web: FeeGroupsScreen"]}],  # consumers also allowed on queues
   "rules": [{"id": "PL-INV-001", ...}], "scenarios": [{"id": "PL-CS-001", ...}]}
Schema versions 1 and 2 (booleans `interfaces_change`, `data_migration` and a `size: minor|major`
verdict) still load: `interfaces_change` true reads as `shape`, `data_migration` true as `reshape`,
and the old `size` is kept as `legacy_size` for sizing.

Every repository must be one the workspace has (codebase/* or the root itself); the LLD scope
defaults to these repositories. Rules and scenarios must be defined in the living docs
(living_docs.py), domains must have a page. `load(..., core_only=True)` keeps an assessment whose
repositories and design facts are valid when only those item lists have problems, so a misspelled
domain never discards what sizing and the LLD scope need.

  impact.py validate --root . --impact <impact.json> [--prd <prd.md>]
Prints one JSON line {valid, repos_csv, count, interface_change, data_change,
infrastructure_change, compatibility_risk, open_decision_count, item_count, scenarios_csv,
issues_summary, summary}; always exits 0.
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

LEGACY_FLAGS = ("interfaces_change", "data_migration", "infrastructure_change")
SIZES = ("minor", "major")
INTERFACE_CHANGES = ("none", "lockstep", "shape")
DATA_CHANGES = ("none", "additive", "reshape")
# open decision kinds: an architecture document answers the blocking ones; the rest an LLD carries
BLOCKING_KINDS = ("placement", "integration", "data-model", "interface", "quality")
DECISION_KINDS = BLOCKING_KINDS + ("rollout", "detail")
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


def load(root, path, core_only=False):
    """-> (impact, issues). impact is None when the file is unusable.

    core_only: problems in the item lists (domains, tables, ..., rules, scenarios) are returned as
    issues but do not discard the repositories and design facts."""
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
    version = doc.get("schema_version", 1)
    if version not in (1, 2, 3):
        issues.append("schema_version must be 1, 2 or 3")
        facts = {}
    elif version == 3:
        facts = _design_facts(doc, issues)
    else:
        facts = _legacy_facts(doc, issues)
    if issues:
        return None, issues
    item_issues = []
    lists = {kind: _items(doc, kind, item_issues) for kind, _key in KINDS}
    _check_docs(root, lists, item_issues)
    if item_issues and not core_only:
        return None, item_issues
    return {"repos": repos, **facts, "summary": str(doc.get("summary") or "").strip(),
            **lists}, item_issues


def _design_facts(doc, issues):
    """The schema-3 design facts sizing decides from; every one is required."""
    for field, allowed in (("interface_change", INTERFACE_CHANGES), ("data_change", DATA_CHANGES)):
        value = str(doc.get(field) or "").strip().lower()
        if value not in allowed:
            issues.append(f"{field} must be one of {', '.join(allowed)}")
    for flag in ("infrastructure_change", "compatibility_risk"):
        if not isinstance(doc.get(flag), bool):
            issues.append(f"{flag} must be true or false")
    decisions = []
    raw = doc.get("open_decisions")
    if not isinstance(raw, list):
        issues.append("open_decisions must be a list (empty when nothing is left to decide)")
        raw = []
    for index, item in enumerate(raw, 1):
        where = f"open_decisions[{index}]"
        if not isinstance(item, dict):
            issues.append(f"{where} must be an object with question, kind and evidence")
            continue
        question = str(item.get("question") or "").strip()
        kind = str(item.get("kind") or "").strip().lower()
        if not question:
            issues.append(f"{where}.question is required, one line")
        if kind not in DECISION_KINDS:
            issues.append(f"{where}.kind must be one of {', '.join(DECISION_KINDS)}")
        if not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            issues.append(f"{where}.evidence is required, one line")
        decisions.append({"question": question, "kind": kind,
                          "evidence": str(item.get("evidence") or "").strip()})
    return {"interface_change": str(doc.get("interface_change") or "").strip().lower(),
            "data_change": str(doc.get("data_change") or "").strip().lower(),
            "infrastructure_change": doc.get("infrastructure_change") is True,
            "compatibility_risk": doc.get("compatibility_risk") is True,
            "open_decisions": decisions, "legacy_size": None}


def _legacy_facts(doc, issues):
    """Schema 1/2 booleans and size, read conservatively as schema-3 facts."""
    for flag in LEGACY_FLAGS:
        if not isinstance(doc.get(flag), bool):
            issues.append(f"{flag} must be true or false")
    size = str(doc.get("size") or "").strip().lower()
    if size not in SIZES:
        issues.append("size must be minor or major")
    return {"interface_change": "shape" if doc.get("interfaces_change") else "none",
            "data_change": "reshape" if doc.get("data_migration") else "none",
            "infrastructure_change": doc.get("infrastructure_change") is True,
            "compatibility_risk": False, "open_decisions": [], "legacy_size": size}


def blocking_decisions(impact):
    """The open decisions an architecture document has to answer."""
    return [d for d in impact.get("open_decisions") or [] if d["kind"] in BLOCKING_KINDS]


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


def describe(impact):
    """One line: the repositories and the design facts, in plain words."""
    repos = impact["repos"]
    parts = [f"{len(repos)} repositor{'y' if len(repos) == 1 else 'ies'} ({', '.join(repos)})"]
    interface = impact["interface_change"]
    if interface == "lockstep":
        parts.append("changing in step with the interface between them unchanged")
    elif interface == "shape":
        parts.append("an interface between repositories changes")
    if impact["data_change"] == "additive":
        parts.append("an additive data change")
    elif impact["data_change"] == "reshape":
        parts.append("stored data changes shape")
    if impact["infrastructure_change"]:
        parts.append("infrastructure changes")
    if impact["compatibility_risk"]:
        parts.append("older clients need a ship order")
    blocking = blocking_decisions(impact)
    parts.append(f"{len(blocking)} open architecture decision{'s' if len(blocking) != 1 else ''}"
                 if blocking else "no open architecture decisions")
    if impact.get("legacy_size"):
        parts.append(f"called {impact['legacy_size']} by an older-format assessment")
    return "; ".join(parts)


def validate(root, path, prd=None):
    impact, issues = load(root, path)
    added = []
    if impact is not None and prd:
        added = _merge_from_prd(root, path, prd)
        if added:
            impact, issues = load(root, path)
    if impact is None:
        return {"valid": False, "repos_csv": "", "count": 0, "interface_change": "",
                "data_change": "", "infrastructure_change": False, "compatibility_risk": False,
                "open_decision_count": 0, "item_count": 0, "scenarios_csv": "",
                "issues_summary": " | ".join(issues[:8]),
                "summary": "Impact assessment is not valid"}
    summary = describe(impact)
    count = sum(len(impact[kind]) for kind, _k in KINDS)
    scenarios = [i["id"] for i in impact["scenarios"]]
    if count:
        summary += f"; {count} impacted items"
    if added:
        summary += f" (engine added scenario{'s' if len(added) > 1 else ''} {', '.join(added)})"
    return {"valid": True, "repos_csv": ",".join(impact["repos"]), "count": len(impact["repos"]),
            "interface_change": impact["interface_change"], "data_change": impact["data_change"],
            "infrastructure_change": impact["infrastructure_change"],
            "compatibility_risk": impact["compatibility_risk"],
            "open_decision_count": len(blocking_decisions(impact)),
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
