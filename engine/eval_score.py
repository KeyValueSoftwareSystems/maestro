#!/usr/bin/env python3
"""Score a finished golden-workflow run against its evaluation case — quality measured, not assumed.

  eval_score.py score   --root <workspace> --case evals/cases/<case> [--judge judge.json]
                        [--out report.json]
  eval_score.py summary --reports <report.json> ... [--baseline evals/baseline.json]

`score` reads the run ledger and artifacts and computes deterministic metrics — run status, design
path, infrastructure level, questions asked and rounds per stage, acceptance criteria, whether the
PRD and HLD pass their validators now, engine verification per repository, the acceptance-criteria
trace, design drift, fix rounds, gates answered by a person or by autopilot, wall time — then
checks the case's `expect:` block. A judge's scores (a subagent grading the artifacts with the
case's rubric.md, saved as {"scores": {criterion: 1-5}, "notes": "..."}) are averaged and checked
against `expect.judge_min`. Prints the report and exits 0 only when every expectation holds.

`summary` aggregates reports and flags regressions against a baseline (a case that passed and now
fails, questions up by more than a quarter, more fix rounds, judge average down by more than 0.5).
Write a new baseline by saving a summary's `cases` object.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ac_trace  # noqa: E402
import state as statemod  # noqa: E402
import validate_hld  # noqa: E402
import validate_prd  # noqa: E402
import wf  # noqa: E402

ASKED = ("accepted-proposal", "chosen-alternative", "user-answer", "assumption", "deferred")
FIX_SUFFIXES = ("/impl/fix", "/bugfix/fix", "/qa/qa_fix")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _outputs(state, path):
    return ((state.get("steps") or {}).get(path) or {}).get("outputs") or {}


def _minutes(state):
    try:
        start = datetime.datetime.fromisoformat(state["created_at"].replace("Z", "+00:00"))
        end = datetime.datetime.fromisoformat(state["updated_at"].replace("Z", "+00:00"))
    except (KeyError, ValueError, AttributeError):
        return None
    return round((end - start).total_seconds() / 60, 1)


def metrics(root, slug):
    state = statemod.load(slug, root) or {}
    run_dir = statemod.feature_dir(slug, root)
    questions, rounds = {}, {}
    for name in sorted(os.listdir(run_dir)) if os.path.isdir(run_dir) else []:
        if name.endswith("-context.json"):
            doc = _read_json(os.path.join(run_dir, name)) or {}
            stage = name[:-len("-context.json")]
            questions[stage] = sum(1 for d in doc.get("decisions") or []
                                   if isinstance(d, dict) and d.get("source") in ASKED)
            rounds[stage] = len(doc.get("rounds") or [])
    prd = os.path.join(run_dir, "requirement", "prd.md")
    hld = os.path.join(run_dir, "hld.md")
    infra_level = _outputs(state, "design/hld/infra_profile").get("level") or "none"
    manifest = _read_json(os.path.join(run_dir, "implementation-manifest.json")) or {}
    statuses = {r.get("repo"): (r.get("verification") or {}).get("status")
                for r in manifest.get("repositories") or []}
    steps = state.get("steps") or {}
    gates = state.get("gates") or []
    return {
        "status": (state.get("run") or {}).get("status"),
        "mode": (state.get("run") or {}).get("mode") or "human",
        "design_path": _outputs(state, "design/sizing").get("path") or "full",
        "infra_level": infra_level,
        "interfaces_changed": _outputs(state, "design/hld/validate_hld").get("interfaces_changed"),
        "questions_asked": sum(questions.values()),
        "questions_by_stage": questions,
        "max_rounds_per_stage": max(rounds.values(), default=0),
        "acceptance_criteria": len(ac_trace.prd_criteria(prd)),
        "prd_valid": os.path.isfile(prd) and not validate_prd.validate(prd)[0],
        "hld_valid": (not validate_hld.validate(hld, infra_level=infra_level)[0])
        if os.path.isfile(hld) else None,
        "verification": statuses,
        "ac_all_passed": _outputs(state, "delivery/ac_trace").get("all_passed"),
        "ac_summary": _outputs(state, "delivery/ac_trace").get("summary"),
        "drift_blocking": _outputs(state, "delivery/drift_verdict").get("blocking"),
        "fix_rounds": sum(entry.get("visits", 0) for path, entry in steps.items()
                          if path.endswith(FIX_SUFFIXES)),
        "person_gates": sum(1 for g in gates if not g.get("auto") and not g.get("synthesized")),
        "autopilot_gates": sum(1 for g in gates if g.get("auto")),
        "minutes": _minutes(state),
    }


def _check(name, expected, actual, passed):
    return {"name": name, "expected": expected, "actual": actual, "passed": bool(passed)}


def evaluate(found, expect, judge=None):
    checks = []
    for key in ("status", "design_path", "infra_level", "interfaces_changed", "prd_valid",
                "hld_valid", "ac_all_passed", "drift_blocking"):
        if key in expect:
            checks.append(_check(key, expect[key], found.get(key), found.get(key) == expect[key]))
    limits = (("max_questions", "questions_asked", "<="), ("max_rounds_per_stage",
              "max_rounds_per_stage", "<="), ("max_fix_rounds", "fix_rounds", "<="),
              ("max_person_gates", "person_gates", "<="),
              ("min_acceptance_criteria", "acceptance_criteria", ">="),
              ("max_acceptance_criteria", "acceptance_criteria", "<="))
    for key, metric, op in limits:
        if key in expect:
            actual = found.get(metric)
            ok = actual is not None and (actual <= expect[key] if op == "<=" else actual >= expect[key])
            checks.append(_check(key, expect[key], actual, ok))
    if expect.get("verification"):
        statuses = found.get("verification") or {}
        ok = bool(statuses) and all(v == expect["verification"] for v in statuses.values())
        checks.append(_check("verification", expect["verification"], statuses, ok))
    if "judge_min" in expect:
        scores = (judge or {}).get("scores") or {}
        average = round(sum(scores.values()) / len(scores), 2) if scores else None
        checks.append(_check("judge_min", expect["judge_min"], average,
                             average is not None and average >= expect["judge_min"]))
    return checks


def cmd_score(args):
    case = wf.load_file(os.path.join(args.case, "case.yaml"))
    found = metrics(args.root, case["slug"])
    judge = _read_json(args.judge) if args.judge else None
    checks = evaluate(found, case.get("expect") or {}, judge)
    failed = [c for c in checks if not c["passed"]]
    report = {"case": case["name"], "passed": not failed,
              "summary": f"{len(checks) - len(failed)}/{len(checks)} expectations met"
                         + (f"; failed: {', '.join(c['name'] for c in failed)}" if failed else ""),
              "metrics": found, "checks": checks,
              "judge": judge}
    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0 if not failed else 1


def cmd_summary(args):
    reports = [r for r in (_read_json(p) for p in args.reports) if r]
    baseline = (_read_json(args.baseline) or {}) if args.baseline else {}
    cases, regressions = {}, []
    for report in reports:
        m = report.get("metrics") or {}
        scores = ((report.get("judge") or {}).get("scores") or {})
        entry = {"passed": report.get("passed"), "questions_asked": m.get("questions_asked"),
                 "fix_rounds": m.get("fix_rounds"),
                 "judge": round(sum(scores.values()) / len(scores), 2) if scores else None}
        cases[report["case"]] = entry
        before = baseline.get(report["case"])
        if not before:
            continue
        if before.get("passed") and not entry["passed"]:
            regressions.append(f"{report['case']}: passed in the baseline, fails now")
        if (before.get("questions_asked") or 0) and (entry["questions_asked"] or 0) > \
                before["questions_asked"] * 1.25:
            regressions.append(f"{report['case']}: questions {before['questions_asked']} -> "
                               f"{entry['questions_asked']}")
        if (entry["fix_rounds"] or 0) > (before.get("fix_rounds") or 0):
            regressions.append(f"{report['case']}: fix rounds {before.get('fix_rounds')} -> "
                               f"{entry['fix_rounds']}")
        if before.get("judge") is not None and entry["judge"] is not None \
                and entry["judge"] < before["judge"] - 0.5:
            regressions.append(f"{report['case']}: judge {before['judge']} -> {entry['judge']}")
    passed = sum(1 for e in cases.values() if e["passed"])
    print(json.dumps({"passed": passed, "total": len(cases),
                      "summary": f"{passed}/{len(cases)} cases passed, "
                                 f"{len(regressions)} regression(s)",
                      "regressions": regressions, "cases": cases}, indent=2))
    return 0 if not regressions and passed == len(cases) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("score")
    p.add_argument("--root", required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--judge")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_score)
    p = sub.add_parser("summary")
    p.add_argument("--reports", nargs="+", required=True)
    p.add_argument("--baseline")
    p.set_defaults(fn=cmd_summary)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
