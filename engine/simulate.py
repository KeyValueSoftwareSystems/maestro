#!/usr/bin/env python3
"""Walk a real workflow graph with zero LLM calls, in seconds — a dev tool for answering
"what happens after X" without a real 15-minute HLD/LLD run.

Reuses the exact engine primitives the real CLI and the no-LLM e2e test suite use
(resolver.init_run/next_action/complete_step/record_gate) against a REAL project root —
so script nodes run for real (codebase_scan.py, lld_repo_pool.py, ...), against your real
codebase/ and real state file locking. Only agent steps are stubbed: instantly "completed"
with placeholder output/artifacts, since those are the slow, token-costing part and this tool
exists specifically to skip them. Gates are the one place a human still decides — interactively
by default, or auto-picking the first option (this pack's convention: the forward-progressing
choice is always listed first) with --auto for a fully hands-off walk of the happy path.

Usage
-----
  python3 simulate.py --root <project> --workflow <rel-path> --slug <slug> \
      [--input k=v ...] [--auto] [--max-steps 500] --allow-script-side-effects

Example (from a project with Maestro installed):
  python3 .maestro/engine/simulate.py --root . --workflow .maestro/workflows/design.yaml \
      --slug sim1 --input feature="add favorites" --auto

The run is a REAL run under .maestro/runs/<slug>/ and script nodes execute against the
project root. The explicit side-effect flag prevents accidental use as a read-only graph
viewer. Existing slugs are refused unless --force is also supplied.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolver  # noqa: E402
import state as statemod  # noqa: E402
import validate as validatemod  # noqa: E402
import codebase_scan  # noqa: E402


def _log(line):
    print(line, flush=True)


def _stub_agent(root, act):
    """Instantly 'complete' an agent step: placeholder text for every declared output field,
    a placeholder file for every declared artifact (unless one's already there — respects a
    prepped fixture the same courtesy the e2e test harness gives it)."""
    step = act["step"]
    for rel in act.get("artifacts", []):
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if not os.path.exists(full):
            if rel.endswith("requirement-questions.json") or rel.endswith("open-questions.json"):
                parts = rel.split("/")
                slug = parts[3] if len(parts) > 3 else "simulation"
                content = {"schema_version": 1, "feature_slug": slug, "questions": []}
                with open(full, "w", encoding="utf-8") as fh:
                    json.dump(content, fh, indent=2)
                    fh.write("\n")
            elif rel.endswith("/tasks.json"):
                parts = rel.split("/")
                slug = parts[3] if len(parts) > 3 else "simulation"
                repo = parts[-2]
                content = {
                    "schema_version": 1, "stack": repo, "feature_slug": slug,
                    "context_manifest": {"read_once": ["simulated"], "reference": []},
                    "slices": [{"group_id": "sim", "task_ids": ["sim-1"]}],
                    "tasks": [{"id": "sim-1", "group_id": "sim",
                               "title": "simulated task", "depends_on": [],
                               "reads": [], "writes": ["simulated.txt"],
                               "test": "simulated", "standards": [],
                               "needs_human_gate": False}],
                }
                with open(full, "w", encoding="utf-8") as fh:
                    json.dump(content, fh, indent=2)
                    fh.write("\n")
            else:
                with open(full, "w", encoding="utf-8") as fh:
                    fh.write(f"# [simulated] {step}\n\nPlaceholder content from engine/simulate.py "
                             f"— this step's real agent was never dispatched.\n")
    if (step.endswith("resync_map") or step.endswith("/build")
            or step.endswith("/retrospect")):
        for _name, repo in codebase_scan.discover_repos(root):
            map_path = os.path.join(repo, codebase_scan.DEFAULT_MAP_REL)
            if (step.endswith("/retrospect")
                    and codebase_scan.read_marker(map_path) == codebase_scan._head(repo)):
                continue
            os.makedirs(os.path.dirname(map_path), exist_ok=True)
            with open(map_path, "a", encoding="utf-8") as fh:
                fh.write("\n# Simulated map refresh\n")
    bool_values = {"blocking": False, "tests_passed": True, "passed": True,
                   "checks_passed": True, "risky": False}
    numeric_fields = {"task_count", "slice_count", "case_count", "failed_count",
                      "lessons_count"}
    outputs = {}
    for field in act.get("outputs", []):
        if field in bool_values:
            outputs[field] = bool_values[field]
        elif field in numeric_fields:
            outputs[field] = 0 if field == "failed_count" else 1
        else:
            outputs[field] = f"[sim] {step}.{field}"
    return outputs


def _choose_gate_option(act, auto):
    options = act["options"]
    if auto:
        return options[0], (f"[auto] placeholder for {options[0].get('input')}"
                             if options[0].get("input") else None)
    _log(f"\n--- gate: {act['step']} ---")
    _log(act["prompt"].rstrip())
    for i, opt in enumerate(options):
        _log(f"  {i + 1}. [{opt['id']}] {opt['label']}")
    while True:
        raw = input("choice (number or id): ").strip()
        match = None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            match = options[int(raw) - 1]
        else:
            match = next((o for o in options if o["id"] == raw), None)
        if match:
            break
        _log(f"unrecognized choice {raw!r}, try again")
    text = None
    if match.get("input"):
        text = input(f"  free text for '{match['input']}': ")
    return match, text


MAX_REPEATED_AUTO_CHOICE = 3


def run(root, slug, workflow, inputs, auto, max_steps, force=False):
    auto_repeat = {}  # (step, option_id) -> consecutive count, for stuck-loop detection
    issues = validatemod.validate_file(workflow, root=root)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        for issue in errors:
            _log(str(issue))
        raise resolver.RunError(f"workflow has {len(errors)} validation error(s)", code=1)

    if os.path.exists(statemod.state_path(slug, root)) and not force:
        raise resolver.RunError(
            f"slug {slug!r} already exists; choose a throwaway slug or pass --force to "
            "explicitly replace its run ledger", code=3,
        )

    with statemod.locked(slug, root):
        resolver.init_run(slug, workflow, inputs, root, force=force)
    _log(f"[init] slug={slug!r} workflow={workflow!r} root={root!r}")

    for step_count in range(max_steps):
        run_obj = resolver.Run(slug, root)
        action = resolver.next_action(run_obj)
        kind = action["action"]
        if kind == "done":
            _log(f"\n[done] outputs: {json.dumps(action.get('outputs', {}), indent=2)}")
            return action
        if kind == "failed":
            _log(f"\n[failed] {action.get('reason')}")
            return action

        batch = action["agents"] if kind == "run_agents" else [action]
        for act in batch:
            step = act["step"]
            # Do the (potentially slow, or lock-taking, e.g. lld_repo_pool.py claim/init)
            # work OUTSIDE the run-state lock — exactly like the real dispatch loop, where the
            # lead agent runs a script/subagent itself and only calls back into a locked
            # complete/gate-record afterward. Holding this lock across a script subprocess
            # that ALSO takes it (same slug+root) would self-deadlock.
            if act["action"] == "run_agent":
                outputs = _stub_agent(root, act)
                _log(f"[agent ] {step} (model={act.get('model')}, skill={act.get('skill')}, "
                     f"stubbed) -> {outputs}")
            elif act["action"] == "run_script":
                env = os.environ.copy()
                env["MAESTRO_SIMULATION"] = "1"
                proc = subprocess.run(act["argv"], cwd=root, capture_output=True,
                                      text=True, timeout=act.get("timeout", 300), env=env)
                _log(f"[script] {step} -> exit={proc.returncode} {proc.stdout.strip()[:200]}")
                if proc.returncode and proc.stderr.strip():
                    _log(f"         stderr: {proc.stderr.strip()[:500]}")
            elif act["action"] == "ask_gate":
                option, text = _choose_gate_option(act, auto)
                _log(f"[gate  ] {step} -> {option['id']}" + (f" ({text})" if text else ""))
                if auto:
                    key = (step, option["id"])
                    auto_repeat[key] = auto_repeat.get(key, 0) + 1
                    if auto_repeat[key] > MAX_REPEATED_AUTO_CHOICE:
                        raise resolver.RunError(
                            f"stuck: gate {step!r} auto-picked {option['id']!r} "
                            f"{auto_repeat[key]} times in a row with no progress — that "
                            f"option likely needs real human action (e.g. 'add files') "
                            f"the simulator can't perform. Re-run without --auto to answer "
                            f"it yourself.", code=1,
                        )

            with statemod.locked(slug, root):
                run_obj = resolver.Run(slug, root)
                if act["action"] == "run_agent":
                    resolver.complete_step(run_obj, step, outputs=outputs)
                elif act["action"] == "run_script":
                    resolver.complete_step(run_obj, step, exit_code=proc.returncode,
                                           stdout=proc.stdout)
                elif act["action"] == "ask_gate":
                    resolver.record_gate(run_obj, step, option["id"], input_text=text)
                statemod.save(slug, run_obj.state, root)
    _log(f"\n[stopped] hit --max-steps ({max_steps}) without finishing")
    return {"action": "stopped"}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="project root (has .maestro/ in it)")
    parser.add_argument("--workflow", required=True, help="workflow file, relative to --root")
    parser.add_argument("--slug", required=True, help="throwaway slug — do not reuse a real one")
    parser.add_argument("--input", action="append", default=[], help="k=v, repeatable")
    parser.add_argument("--auto", action="store_true",
                        help="auto-pick the first gate option instead of prompting")
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--force", action="store_true",
                        help="replace an existing run ledger for this slug")
    parser.add_argument(
        "--allow-script-side-effects", action="store_true",
        help="required acknowledgement: workflow script nodes run against --root for real",
    )
    args = parser.parse_args(argv[1:])

    inputs = {}
    for pair in args.input:
        if "=" not in pair:
            raise resolver.RunError(f"--input expects k=v, got {pair!r}", code=3)
        key, value = pair.split("=", 1)
        inputs[key] = value

    if not args.allow_script_side_effects:
        raise resolver.RunError(
            "simulation runs real script nodes and may write to --root; re-run with "
            "--allow-script-side-effects using a throwaway slug", code=3,
        )

    result = run(args.root, args.slug, args.workflow, inputs, args.auto,
                 args.max_steps, force=args.force)
    return {"done": 0, "failed": 1, "stopped": 2}.get(result.get("action"), 1)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except resolver.RunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(exc.code)
