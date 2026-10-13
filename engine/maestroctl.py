#!/usr/bin/env python3
"""maestroctl — the deterministic engine CLI behind the Maestro lead agent.

The lead agent's whole protocol:

    maestroctl validate <workflow>
    maestroctl init --slug S --workflow <workflow> [--input k=v ...]
    loop:
        maestroctl next --slug S [--serial]          # ONE action as JSON (claims workers)
        # dispatch it, then one of:
        maestroctl complete --slug S --step P --outputs '<json>'
        maestroctl complete-batch --slug S --results '[{"step":P,"outputs":{...}}, ...]'
        maestroctl complete --slug S --step P --exit-code N [--stdout '<text>']
        maestroctl gate-record --slug S --step P --option X [--input '<text>']
        maestroctl gate-input-record --slug S --step P --input '<text>'
        maestroctl interview-record --slug S --step P --section X (--accept | --answer '<text>')
        maestroctl interview-record-batch --slug S --step P --responses '<json>'
        maestroctl fail --slug S --step P --reason '<why>'

Also: status, reset (--step/--all, --cascade), rebase, graph, runs, workstreams, note,
upgrade-run, and correction-record. `next --peek` re-reads without claiming or running.

Every serving command (next, complete, gate-record, ...) first runs pending ENGINE-OWNED script
steps itself — argv `python3 .maestro/engine/<script>.py ...` — and completes them, so the lead
never round-trips them; the action lists them under `auto_scripts`. Other scripts are still
served as `run_script`. Disable with MAESTRO_AUTO_SCRIPTS=0. Worker steps are claimed when
served: later calls return only newly ready work (or `wait`), and `init` releases the claims
of a resumed run so lost workers are re-served.

Exit codes: 0 ok · 1 validation errors · 2 internal error · 3 setup/hash problem ·
4 invalid transition (wrong step, missing outputs/artifacts, unknown option).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

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
        if not created and resolver.release_claims(data):
            # Resume: workers handed out by a previous session are gone — re-serve them.
            statemod.save(args.slug, data, args.root)
    _print({
        "ok": True,
        "created": created,
        "slug": args.slug,
        "workflow": data["workflow"]["file"],
        "cursors": data["run"]["cursors"],
        "status": data["run"]["status"],
    })
    return 0


MAX_AUTO_SCRIPTS = 200  # backstop; script visit caps bound real loops long before this


def _auto_scripts_enabled():
    return os.environ.get("MAESTRO_AUTO_SCRIPTS", "1").strip().lower() not in ("0", "false", "no")


def _engine_owned(argv, root):
    """True for `python3 .maestro/engine/<x>.py ...` — pack code the engine may run itself."""
    if len(argv) < 2 or os.path.basename(argv[0]) not in ("python3", "python"):
        return False
    engine_dir = os.path.realpath(os.path.join(root, ".maestro", "engine"))
    script = os.path.realpath(os.path.join(root, argv[1]))
    return script.startswith(engine_dir + os.sep) and script.endswith(".py")


def _run_engine_script(action, root):
    argv = [sys.executable, *action["argv"][1:]]
    timeout = action.get("timeout") or resolver.DEFAULT_SCRIPT_TIMEOUT
    try:
        proc = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, str(exc)
    out = proc.stdout
    if proc.returncode != 0 and not out.strip():
        out = proc.stderr[-2000:]
    return proc.returncode, out


def _serve_action(args, peek=False):
    """The next action the lead must handle, after running engine-owned scripts.

    Scripts run OUTSIDE the ledger lock: several engine helpers take that lock themselves.
    Their completion re-checks under the lock that the step is still the active visit.
    """
    serial = getattr(args, "serial", False)
    if peek:
        return resolver.next_action(resolver.Run(args.slug, args.root), serial=serial)
    ran = []
    auto = _auto_scripts_enabled()
    for _ in range(MAX_AUTO_SCRIPTS):
        with statemod.locked(args.slug, args.root):
            run = resolver.Run(args.slug, args.root)
            action = resolver.next_action(run, serial=serial, claim=True)
            if action["action"] in ("run_agent", "run_agents"):
                statemod.save(args.slug, run.state, args.root)
            visits = (run.state["steps"].get(action.get("step") or "") or {}).get("visits")
        if not (auto and action["action"] == "run_script"
                and _engine_owned(action["argv"], args.root)):
            break
        started = time.monotonic()
        code, out = _run_engine_script(action, args.root)
        with statemod.locked(args.slug, args.root):
            run = resolver.Run(args.slug, args.root)
            entry = run.state["steps"].get(action["step"]) or {}
            if (action["step"] not in (run.state["run"].get("cursors") or [])
                    or entry.get("visits") != visits):
                continue  # superseded while it ran (e.g. a concurrent reset) — re-serve
            resolver.complete_step(run, action["step"], exit_code=code, stdout=out,
                                   telemetry={"executor": "engine"})
            statemod.save(args.slug, run.state, args.root)
        ran.append({"step": action["step"], "exit_code": code,
                    "seconds": round(time.monotonic() - started, 1)})
    if ran:
        action = {**action, "auto_scripts": ran}
    return action


def _serve(args, peek=False):
    _print(_serve_action(args, peek=peek))
    return 0


def cmd_next(args):
    return _serve(args, peek=args.peek)


def _mutate(args, fn):
    with statemod.locked(args.slug, args.root):
        run = resolver.Run(args.slug, args.root)
        fn(run)
        statemod.save(args.slug, run.state, args.root)
    return _serve(args)


def cmd_complete(args):
    outputs = None
    if args.outputs:
        try:
            outputs = json.loads(args.outputs)
        except ValueError as exc:
            raise resolver.RunError(f"--outputs is not valid JSON: {exc}", code=4)
        if not isinstance(outputs, dict):
            raise resolver.RunError("--outputs must be a JSON object", code=4)
    telemetry = None
    if args.telemetry:
        try:
            telemetry = json.loads(args.telemetry)
        except ValueError as exc:
            raise resolver.RunError(f"--telemetry is not valid JSON: {exc}", code=4)
        if not isinstance(telemetry, dict):
            raise resolver.RunError("--telemetry must be a JSON object", code=4)
    return _mutate(args, lambda run: resolver.complete_step(
        run, args.step, outputs=outputs, exit_code=args.exit_code, stdout=args.stdout,
        telemetry=telemetry,
    ))


def cmd_complete_batch(args):
    """Record a finished parallel wave in one call; one returned action to act on."""
    try:
        results = json.loads(args.results)
    except ValueError as exc:
        raise resolver.RunError(f"--results is not valid JSON: {exc}", code=4) from None
    if not isinstance(results, list) or not all(
            isinstance(r, dict) and isinstance(r.get("step"), str) for r in results):
        raise resolver.RunError(
            '--results must be a JSON list of {"step": ..., "outputs": {...}} or '
            '{"step": ..., "fail": "<reason>"}', code=4)
    report = []

    def fn(run):
        # Each result applies independently: one invalid completion (missing artifact/field)
        # is reported back for the lead's retry protocol and never blocks its siblings.
        for item in results:
            try:
                if "fail" in item:
                    resolver.fail_step(run, item["step"], str(item["fail"]))
                    report.append({"step": item["step"], "status": "failed-recorded"})
                else:
                    resolver.complete_step(run, item["step"], outputs=item.get("outputs") or {},
                                           telemetry=item.get("telemetry"))
                    report.append({"step": item["step"], "status": "done"})
            except resolver.RunError as exc:
                report.append({"step": item["step"], "status": "error", "error": str(exc)})

    with statemod.locked(args.slug, args.root):
        run = resolver.Run(args.slug, args.root)
        fn(run)
        statemod.save(args.slug, run.state, args.root)
    _print({**_serve_action(args), "batch": report})
    return 4 if any(r["status"] == "error" for r in report) else 0


def cmd_gate_record(args):
    return _mutate(args, lambda run: resolver.record_gate(
        run, args.step, args.option, input_text=args.input,
    ))


def cmd_gate_input_record(args):
    return _mutate(args, lambda run: resolver.record_gate_input(
        run, args.step, args.input,
    ))


def cmd_interview_record(args):
    return _mutate(args, lambda run: resolver.record_interview(
        run, args.step, args.section, answer=args.answer, accept=args.accept,
    ))


def cmd_interview_record_batch(args):
    try:
        responses = json.loads(args.responses)
    except ValueError as exc:
        raise resolver.RunError(f"--responses is not valid JSON: {exc}", code=4) from None
    if not isinstance(responses, dict):
        raise resolver.RunError("--responses must be a JSON object", code=4)
    return _mutate(args, lambda run: resolver.record_interview_batch(
        run, args.step, responses,
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


def cmd_upgrade_run(args):
    import run_upgrade
    result = (
        run_upgrade.apply(args.slug, args.root, args.workflow)
        if args.apply else run_upgrade.inspect(args.slug, args.root, args.workflow)
    )
    _print(result)
    return 0


def cmd_correction_record(args):
    import design_corrections
    result = design_corrections.record(
        args.slug, args.root, args.scope, args.text, repo=args.repo,
        parent_slug=args.parent_slug,
    )
    _print(result)
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
    print(f"{'step'.ljust(width)}  {'status'.ljust(8)}  visits  duration  outputs")
    for path in sorted(data["steps"]):
        entry = data["steps"][path]
        keys = ",".join(entry.get("outputs") or {}) or "-"
        duration = f"{entry['duration_ms']}ms" if "duration_ms" in entry else "-"
        print(f"{path.ljust(width)}  {str(entry.get('status')).ljust(8)}  "
              f"{str(entry.get('visits', 0)).ljust(6)}  {duration.ljust(8)}  {keys}")
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


def cmd_workstreams(args):
    import lld_repo_pool
    _print(lld_repo_pool.workstream_summary(args.slug, args.root))
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

    p = sub.add_parser("next", help="serve the next action as JSON (claims workers, runs "
                                    "engine scripts)")
    p.add_argument("--slug", required=True)
    p.add_argument("--serial", action="store_true", help="never batch parallel agents")
    p.add_argument("--peek", action="store_true",
                   help="read-only: show the current action without claiming or running")
    p.set_defaults(fn=cmd_next)

    p = sub.add_parser("complete-batch", help="record a finished parallel wave in one call")
    p.add_argument("--slug", required=True)
    p.add_argument("--results", required=True,
                   help='JSON list of {"step","outputs"} or {"step","fail"} objects')
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_complete_batch)

    p = sub.add_parser("complete", help="record a finished agent/script step and advance")
    p.add_argument("--slug", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--outputs", help="JSON object the subagent returned")
    p.add_argument("--exit-code", type=int, help="script exit code")
    p.add_argument("--stdout", help="script stdout (last line parsed as JSON outputs)")
    p.add_argument("--telemetry", help="optional factual JSON metrics from the host")
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_complete)

    p = sub.add_parser("gate-record", help="record a human gate decision and advance")
    p.add_argument("--slug", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--option", required=True)
    p.add_argument("--input", help="free text collected by the option")
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_gate_record)

    p = sub.add_parser("gate-input-record", help="record required free text after a gate choice")
    p.add_argument("--slug", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--input", required=True, help="free text requested by the pending gate option")
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_gate_input_record)

    p = sub.add_parser("interview-record", help="confirm the current interview section")
    p.add_argument("--slug", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--section", required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--accept", action="store_true", help="accept the engine-served proposal")
    group.add_argument("--answer", help="confirmed replacement answer")
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_interview_record)

    p = sub.add_parser(
        "interview-record-batch", help="confirm clear answers from a served interview batch",
    )
    p.add_argument("--slug", required=True)
    p.add_argument("--step", required=True)
    p.add_argument(
        "--responses", required=True,
        help='JSON object: {"question-id":{"accept":true}, "other":{"answer":"text"}}',
    )
    p.add_argument("--serial", action="store_true")
    p.set_defaults(fn=cmd_interview_record_batch)

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

    p = sub.add_parser(
        "upgrade-run", help="inspect or apply the one-time current-format run upgrade",
    )
    p.add_argument("--slug", required=True)
    p.add_argument("--workflow", default=".maestro/workflows/sdlc-main.yaml")
    p.add_argument(
        "--apply", action="store_true",
        help="back up and upgrade after the human accepts the inspection preview",
    )
    p.set_defaults(fn=cmd_upgrade_run)

    p = sub.add_parser(
        "correction-record", help="record one human-approved effective-design correction",
    )
    p.add_argument("--slug", required=True, help="feature parent or repository LLD child")
    p.add_argument("--parent-slug", help="explicit feature parent (normally inferred)")
    p.add_argument(
        "--scope", required=True,
        choices=("product", "architecture", "repository", "contract", "verification", "cross-cutting"),
    )
    p.add_argument("--repo", help="required for repository scope unless inferred from a child")
    p.add_argument("--text", required=True, help="the approved correction, verbatim")
    p.set_defaults(fn=cmd_correction_record)

    p = sub.add_parser("status", help="human-readable run status")
    p.add_argument("--slug", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("graph", help="nodes+edges JSON for a workflow file (UI helper)")
    p.add_argument("workflow")
    p.set_defaults(fn=cmd_graph)

    p = sub.add_parser("runs", help="list every run under .maestro/runs/ as JSON (read-only)")
    p.set_defaults(fn=cmd_runs)

    p = sub.add_parser(
        "workstreams", help="list repo-owned LLD child runs for resume selection (read-only)",
    )
    p.add_argument("--slug", required=True, help="parent feature or repo LLD child slug")
    p.set_defaults(fn=cmd_workstreams)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    # Validate the slug at the CLI boundary, before any command touches the filesystem
    # (the lock context creates .maestro/runs/<slug>/ — a bad slug must be rejected first).
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
