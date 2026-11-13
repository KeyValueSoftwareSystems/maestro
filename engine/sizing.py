#!/usr/bin/env python3
"""Size a feature after PRD approval: the full design path, or the light path for a small change.

  sizing.py [--root .] --prd <prd.md> [--impact <impact.json>] [--hld <hld.md>] [--path auto|full|light]

The light path skips the HLD and the contract: the PRD goes straight to the repository LLD,
readiness check and approval (the test cases are written from the PRD alongside, on either
path). The impact assessment (impact.py) records facts, never a
verdict; `auto` (the default) takes the light path unless one of them needs an architecture
document —
  - an open decision of a blocking kind (placement, integration, data-model, interface, quality),
  - an interface between repositories changes shape, stored data changes shape (reshape),
    or infrastructure changes,
  - the PRD still has "(to confirm)" marks,
  - an HLD exists from an earlier pass (a revision never silently drops an approved architecture),
  - an older-format assessment called the feature `major`.
How many repositories change never decides: several repositories changing in step under an
unchanged interface is still a light change. Repositories, interface and data facts come from a
core-valid assessment (impact.load core_only), so a misspelled domain in its item lists does not
discard them. Without one (a new product skips it, or it never validated) the rules decide, all of
which must hold for light —
  - at most `design.light_max_criteria` acceptance criteria (maestro.config.yaml, default 5),
  - Non-functional requirements says None (no targets to design for),
  - the workspace holds exactly one repository,
  - nothing in the PRD is still marked "(to confirm)".
`full` and `light` force a path (a person's choice at run start). Prints one JSON line
{path, reasons, summary, explanation, greenfield, forced}: `explanation` says in plain words what
the choice means, for the person who may switch it; always exits 0.

  sizing.py choose [--root .] --sized <light|full> [--choice accept|plan|direct]
The person's answer to the design-path gate: `plan` -> full, `direct` -> light, anything else
(accept, or empty when the gate was skipped) keeps the sized path. Light is refused when the
workspace has no repository yet. Prints {path, summary}; always exits 0.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ac_trace  # noqa: E402
import codebase_scan  # noqa: E402
import impact as impactmod  # noqa: E402
import validate_prd  # noqa: E402

MAX_CRITERIA = 5
PATHS = ("auto", "full", "light")
CHOICES = {"plan": "full", "direct": "light"}
NEXT = {"light": "Next: a detailed plan for each repository it changes, then the build.",
        "full": "Next: an architecture document (you can talk it through first), then a "
                "detailed plan for each repository."}


def max_criteria(root):
    try:
        import project_config
        config = project_config.load(root) or {}
    except Exception:  # an unreadable config is preflight's to report
        config = {}
    value = (config.get("design") or {}).get("light_max_criteria") \
        if isinstance(config, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 \
        else MAX_CRITERIA


def _abs(root, path):
    return path if os.path.isabs(path) else os.path.join(root, path)


def _has_file(root, path):
    try:
        return bool(path) and os.path.getsize(_abs(root, path)) > 0
    except OSError:
        return False


def _join(names):
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _from_impact(impact, text, root, hld_path):
    """-> (path, reasons, explanation) from a core-valid assessment's facts."""
    blockers = [(f"open decision ({d['kind']}): {d['question']}", d["question"])
                for d in impactmod.blocking_decisions(impact)]
    if impact["interface_change"] == "shape":
        blockers.append(("an interface between repositories changes shape",
                         "an interface between repositories changes shape (an endpoint, event or "
                         "field is added, changed or removed)"))
    if impact["data_change"] == "reshape":
        blockers.append(("stored data changes shape",
                         "stored data changes shape (a new entity, a type change or a backfill)"))
    if impact["infrastructure_change"]:
        blockers.append(("infrastructure changes", "infrastructure changes"))
    if validate_prd.TO_CONFIRM_RE.search(text):
        blockers.append(("PRD still has (to confirm) marks",
                         "the PRD still has points marked (to confirm)"))
    if _has_file(root, hld_path):
        blockers.append(("an HLD exists from an earlier pass",
                         "an architecture document was already written for this feature"))
    if impact.get("legacy_size") == "major":
        blockers.append(("an older-format impact assessment classifies it as major",
                         "an older-format impact assessment called it a major change"))
    if blockers:
        lines = "\n".join(f"- {plain}" for _reason, plain in blockers)
        return "full", [reason for reason, _plain in blockers], (
            f"This needs architecture decisions before the detailed plans:\n{lines}\n{NEXT['full']}")
    repos = impact["repos"]
    if len(repos) == 1:
        who = f"only {repos[0]} changes"
    elif impact["interface_change"] == "lockstep":
        who = f"{_join(repos)} change in step"
    else:
        who = f"{_join(repos)} change, each on its own"
    reason = (f"{len(repos)} repositor{'y' if len(repos) == 1 else 'ies'} ({', '.join(repos)}), "
              f"interface {impact['interface_change']}, data {impact['data_change']}, "
              "no infrastructure change, no open architecture decisions")
    explanation = (f"This looks like a contained change: {who}. Nothing new to decide about how "
                   "the system fits together: no interface or stored data changes shape and no "
                   "infrastructure changes.")
    if impact["compatibility_risk"]:
        explanation += (" Older app versions or clients need care, so the plans will say what "
                        "ships first.")
        reason += "; older clients need a ship order"
    left = [d["question"] for d in impact["open_decisions"] if d["kind"] not in impactmod.BLOCKING_KINDS]
    if left:
        explanation += "\nLeft for the detailed plans:\n" + "\n".join(f"- {q}" for q in left)
    return "light", [reason], f"{explanation}\n{NEXT['light']}"


def _from_rules(root, full, text):
    """-> (path, reasons, explanation) without an assessment."""
    criteria = ac_trace.prd_criteria(full)
    nfr = validate_prd._sections(text).get("non functional requirements", "").strip()
    limit = max_criteria(root)
    repos = codebase_scan.discover_repos(root)
    blockers = []
    if len(criteria) > limit:
        blockers.append(f"{len(criteria)} acceptance criteria (light allows {limit})")
    if not re.match(r"^none\b", nfr, re.IGNORECASE):
        blockers.append("non-functional targets to design for")
    if len(repos) != 1:
        blockers.append(f"{len(repos)} repositories in the workspace (light needs exactly one)")
    if validate_prd.TO_CONFIRM_RE.search(text):
        blockers.append("PRD still has (to confirm) marks")
    if not repos:
        return "full", blockers, ("This is a new product with no code yet, so the architecture "
                                  f"comes first.\n{NEXT['full']}")
    if blockers:
        lines = "\n".join(f"- {b}" for b in blockers)
        return "full", blockers, ("There is no impact assessment to size this feature from, so it "
                                  f"is planned in full:\n{lines}\n{NEXT['full']}")
    reason = f"{len(criteria)} acceptance criteria, no non-functional targets, one repository"
    return "light", [reason], (f"This looks like a small change: {reason}, nothing left to "
                               f"confirm.\n{NEXT['light']}")


def size(root, prd_path, requested="auto", impact_path=None, hld_path=None):
    """-> {path, reasons, explanation, greenfield, forced}."""
    full = _abs(root, prd_path)
    try:
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    greenfield = not codebase_scan.discover_repos(root)
    if requested in ("full", "light"):
        return {"path": requested, "reasons": [f"path {requested} requested at run start"],
                "explanation": f"The {requested} design path was chosen when the run started.",
                "greenfield": greenfield, "forced": True}
    impact = impactmod.load(root, impact_path, core_only=True)[0] if impact_path else None
    if impact:
        path, reasons, explanation = _from_impact(impact, text, root, hld_path)
    else:
        path, reasons, explanation = _from_rules(root, full, text)
    return {"path": path, "reasons": reasons, "explanation": explanation,
            "greenfield": greenfield, "forced": False}


def _summary(path, reasons):
    return ("Light path: PRD → LLD (no HLD or contract) — " if path == "light"
            else "Full design path — ") + "; ".join(reasons)


def choose(root, sized, choice):
    """-> {path, summary}: the person's answer to the design-path gate applied to the sized path."""
    sized = sized if sized in ("light", "full") else "full"
    choice = (choice or "").strip().lower()
    path = CHOICES.get(choice, sized)
    how = "chosen by the person" if choice in CHOICES and path != sized else "as sized"
    if path == "light" and not codebase_scan.discover_repos(root):
        return {"path": "full", "summary": "Full design path — the workspace has no repository "
                                           "yet, so the architecture comes first"}
    return {"path": path, "summary": _summary(path, [how])}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["choose"]:
        parser = argparse.ArgumentParser(prog="sizing.py choose")
        parser.add_argument("--root", default=".")
        parser.add_argument("--sized", default="full")
        parser.add_argument("--choice", default="")
        args = parser.parse_args(argv[1:])
        print(json.dumps(choose(args.root, args.sized, args.choice)))
        return 0
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    parser.add_argument("--prd", required=True)
    parser.add_argument("--impact", default="",
                        help="the impact assessment; empty: size by the PRD rules")
    parser.add_argument("--hld", default="", help="the feature's HLD path (exists on a revision pass)")
    parser.add_argument("--path", default="auto")
    args = parser.parse_args(argv)
    requested = args.path if args.path in PATHS else "auto"
    result = size(args.root, args.prd, requested, args.impact or None, args.hld or None)
    print(json.dumps({"path": result["path"], "reasons": "; ".join(result["reasons"]),
                      "summary": _summary(result["path"], result["reasons"]),
                      "explanation": result["explanation"], "greenfield": result["greenfield"],
                      "forced": result["forced"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
