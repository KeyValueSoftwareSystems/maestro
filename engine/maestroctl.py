#!/usr/bin/env python3
"""maestroctl — the deterministic engine CLI behind the /maestro lead agent.

The lead agent's whole protocol:

    maestroctl validate <workflow>
    maestroctl init --slug S --workflow <workflow> [--input k=v ...]
    loop:
        maestroctl next --slug S [--serial]          # ONE action as JSON
        # dispatch it, then one of:
        maestroctl complete --slug S --step P --outputs '<json>'
        maestroctl complete --slug S --step P --exit-code N [--stdout '<text>']
        maestroctl gate-record --slug S --step P --option X [--input '<text>']
        maestroctl fail --slug S --step P --reason '<why>'

Also: status, reset (--step/--all, --cascade), rebase, graph, note (capture out-of-band input).

Exit codes: 0 ok · 1 validation errors · 2 internal error · 3 setup/hash problem ·
4 invalid transition (wrong step, missing outputs/artifacts, unknown option).
"""

from __future__ import annotations

import argparse
import json
import sys

import resolver
import state as statemod
import validate as validatemod


def _print(obj):
    print(json.dumps(obj, indent=2))


def cmd_validate(args):
    issues = validatemod.validate_file(args.workflow, root=args.root)
    errors = [i for i in issues if i.level == "error"]
    for issue in issues:
        print(str(issue), file=sys.stderr)
    _print({
        "ok": not errors,
        "errors": len(errors),
        "warnings": len(issues) - len(errors),
    })
    return 1 if errors else 0


def cmd_init(args):
    inputs = {}
    for pair in args.input or []:
        if "=" not in pair:
            raise resolver.RunError(f"--input expects k=v, got {pair!r}", code=3)
        key, value = pair.split("=", 1)
        inputs[key] = value
    issues = validatemod.validate_file(args.workflow, root=args.root)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        for issue in errors:
            print(str(issue), file=sys.stderr)
        raise resolver.RunError(f"workflow has {len(errors)} validation error(s); fix them first", code=1)
    with statemod.locked(args.slug, args.root):
        data, created = resolver.init_run(args.slug, args.workflow, inputs, args.root, force=args.force)
    _print({
        "ok": True,
        "created": created,
        "slug": args.slug,
        "workflow": data["workflow"]["file"],
        "cursors": data["run"]["cursors"],
        "status": data["run"]["status"],
    })
    return 0


def cmd_next(args):
    run = resolver.Run(args.slug, args.root)
    action = resolver.next_action(run, serial=args.serial)
    _print(action)
    return 0


def _mutate(args, fn):
    with statemod.locked(args.slug, args.root):
        run = resolver.Run(args.slug, args.root)
        fn(run)
        statemod.save(args.slug, run.state, args.root)
        action = resolver.next_action(run, serial=getattr(args, "serial", False))
    _print(action)
    return 0


def cmd_complete(args):
    outputs = None
    if args.outputs:
        try:
            outputs = json.loads(args.outputs)
        except ValueError as exc:
            raise resolver.RunError(f"--outputs is not valid JSON: {exc}", code=4)
        if not isinstance(outputs, dict):
            raise resolver.RunError("--outputs must be a JSON object", code=4)
    return _mutate(args, lambda run: resolver.complete_step(
        run, args.step, outputs=outputs, exit_code=args.exit_code, stdout=args.stdout,
    ))


def cmd_gate_record(args):
    return _mutate(args, lambda run: resolver.record_gate(
        run, args.step, args.option, input_text=args.input,
    ))


def cmd_fail(args):
    return _mutate(args, lambda run: resolver.fail_step(run, args.step, args.reason))


def cmd_reset(args):
    if not args.all and not args.step:
        raise resolver.RunError("reset needs --step ... or --all", code=4)

    def fn(run):
        if args.all:
            resolver.reset_all(run)
        else:
            resolver.reset_steps(run, args.step, cascade=args.cascade)

    return _mutate(args, fn)


def cmd_rebase(args):
    def fn(run):
        resolver.rebase(run)

    return _mutate(args, fn)


def cmd_note(args):
    with statemod.locked(args.slug, args.root):
        run = resolver.Run(args.slug, args.root)
        resolver.record_note(run, args.text, step=args.step)
        statemod.save(args.slug, run.state, args.root)
    _print({"ok": True, "notes": len(run.state.get("notes") or [])})
    return 0


def cmd_status(args):
    data = statemod.load(args.slug, args.root)
    if data is None:
        print(f"no run for slug {args.slug!r}", file=sys.stderr)
        return 3
    if args.json:
        _print(data)
        return 0
    run_info = data["run"]
    print(f"slug:     {data['slug']}")
    print(f"workflow: {data['workflow']['file']}")
    print(f"status:   {run_info['status']}")
    print(f"active:   {', '.join(run_info.get('cursors') or []) or '-'}")
    print()
    width = max((len(p) for p in data["steps"]), default=10)
    print(f"{'step'.ljust(width)}  {'status'.ljust(8)}  visits  outputs")
    for path in sorted(data["steps"]):
        entry = data["steps"][path]
        keys = ",".join(entry.get("outputs") or {}) or "-"
        print(f"{path.ljust(width)}  {str(entry.get('status')).ljust(8)}  "
              f"{str(entry.get('visits', 0)).ljust(6)}  {keys}")
    if data.get("gates"):
        print()
        print("gate decisions:")
        for g in data["gates"]:
            extra = f" input={g['input']!r}" if g.get("input") else ""
            print(f"  {g['at']}  {g['step']} -> {g['option']}{extra}")
    return 0


def cmd_runs(args):
    _print({"runs": statemod.list_runs(args.root)})
    return 0


def cmd_graph(args):
    import wf as wfmod

    doc = wfmod.load_file(args.workflow)
    nodes, edges = [], []
    for node in doc.get("nodes") or []:
        nodes.append({
            "id": node.get("id"), "type": node.get("type"),
            "label": node.get("label") or node.get("id"), "ui": node.get("ui") or {},
        })
        nid = node.get("id")
        if node.get("next"):
            edges.append({"from": nid, "to": node["next"], "kind": "next"})
        for route in node.get("routes") or []:
            edges.append({"from": nid, "to": route.get("to"), "kind": "route",
                          "label": route.get("when") or "default"})
        for option in node.get("options") or []:
            edges.append({"from": nid, "to": option.get("to"), "kind": "option",
                          "label": option.get("label")})
        for key in ("on_fail", "on_exhausted"):
            value = node.get(key)
            if value and value not in ("abort", "ask"):
                edges.append({"from": nid, "to": value, "kind": key})
    _print({"name": doc.get("name"), "start": doc.get("start"), "nodes": nodes, "edges": edges})
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="maestroctl", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="repo root (default: cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="lint a workflow file (recursing into subworkflows)")
    p.add_argument("workflow")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("init", help="create or resume the run ledger for a slug")
    p.add_argument("--slug", required=True)
    p.add_argument("--workflow", required=True)
    p.add_argument("--input", action="append", metavar="K=V")
    p.add_argument("--force", action="store_true", help="restart even if a run exists")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("next", help="print the next action as JSON (read-only)")
    p.add_argument("--slug", required=True)
    p.add_argument("--serial", action="store_true", help="never batch parallel agents")
    p.set_defaults(fn=cmd_next)

    p = sub.add_parser("complete", help="record a finished agent/script step and advance")
    p.add_argument("--slug", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--outputs", help="JSON object the subagent returned")
    p.add_argument("--exit-code", type=int, help="script exit code")
    p.add_argument("--stdout", help="script stdout (last line parsed as JSON outputs)")
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_complete)

    p = sub.add_parser("gate-record", help="record a human gate decision and advance")
    p.add_argument("--slug", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--option", required=True)
    p.add_argument("--input", help="free text collected by the option")
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_gate_record)

    p = sub.add_parser("fail", help="record a step failure (engine applies retries/on_fail)")
    p.add_argument("--slug", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_fail)

    p = sub.add_parser("reset", help="force steps back to pending")
    p.add_argument("--slug", required=True)
    p.add_argument("--step", action="append", metavar="PATH")
    p.add_argument("--cascade", action="store_true", help="also reset downstream done steps")
    p.add_argument("--all", action="store_true")
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_reset)

    p = sub.add_parser("rebase", help="accept edited workflow files (re-hash)")
    p.add_argument("--slug", required=True)
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_rebase)

    p = sub.add_parser("note", help="append an out-of-band user instruction to the ledger")
    p.add_argument("--slug", required=True)
    p.add_argument("--text", required=True, help="the user's instruction, verbatim")
    p.add_argument("--step", help="step it relates to (default: the active step[s])")
    p.set_defaults(fn=cmd_note)

    p = sub.add_parser("status", help="human-readable run status")
    p.add_argument("--slug", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("graph", help="nodes+edges JSON for a workflow file (UI helper)")
    p.add_argument("workflow")
    p.set_defaults(fn=cmd_graph)

    p = sub.add_parser("runs", help="list every run under .maestro/ as JSON (read-only)")
    p.set_defaults(fn=cmd_runs)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    # Validate the slug at the CLI boundary, before any command touches the filesystem
    # (the lock context creates .maestro/<slug>/ — a bad slug must be rejected first).
    slug = getattr(args, "slug", None)
    if slug is not None and not statemod.valid_slug(slug):
        print(f"error: invalid slug {slug!r}: use lowercase letters, digits, '.', '-', "
              f"'_' (a single path segment, no '/' or '..')", file=sys.stderr)
        return 3
    try:
        return args.fn(args)
    except resolver.RunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
