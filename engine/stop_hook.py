#!/usr/bin/env python3
"""Claude Code **Stop hook** — auto-continue an active Maestro run (opt-in).

When Claude tries to end its turn, this asks the engine whether the active run
still has AUTONOMOUS work pending — an agent/script action, not a human gate. If so
it blocks the stop (exit 2) and tells the lead agent to keep driving the dispatch
loop. At a human gate, when the run is done/failed, or when nothing is running, it
lets the turn end normally (exit 0) — the human is meant to be in charge at gates.

It is **read-only**: it calls the same next-action resolver the loop uses, which does
NOT write state (`maestroctl next` never saves). A Stop hook must never crash or trap
the user, so every failure path falls through to exit 0 (allow the stop). Claude Code
also re-runs the hook with `stop_hook_active: true` after it blocks, and hard-caps
consecutive blocks — both are honoured below.

This file ships with the engine but is OFF by default. Enable it by adding to
`.claude/settings.json` (see the README, "Pausing & resuming a run"):

    {"hooks": {"Stop": [{"hooks": [
      {"type": "command", "command": "python3 .maestro/engine/stop_hook.py"}]}]}}
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

AUTONOMOUS = {"run_agent", "run_agents", "run_script"}


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # no parseable input — never trap the user

    # Set true when this stop was already triggered by the hook: bail so a stuck run
    # can always end (Claude Code also overrides after 8 consecutive blocks).
    if payload.get("stop_hook_active"):
        return 0

    root = payload.get("cwd") or os.getcwd()

    try:
        import resolver
    except Exception:
        return 0

    pending = []
    for state_path in glob.glob(os.path.join(root, ".maestro", "runs", "*", "state.yaml")):
        slug = os.path.basename(os.path.dirname(state_path))
        try:
            run = resolver.Run(slug, root)
            if (run.state.get("run") or {}).get("status") != "running":
                continue
            action = resolver.next_action(run)
        except Exception:
            continue  # unreadable / changed-workflow halt / mid-step — skip, don't trap
        if action.get("action") in AUTONOMOUS:
            pending.append((slug, action.get("action")))

    if not pending:
        return 0

    slug, kind = pending[0]
    print(
        f"Maestro run '{slug}' still has autonomous work pending (next action: {kind}). "
        f"Do not stop — continue the dispatch loop: run `python3 .maestro/engine/maestroctl.py "
        f"next --slug {slug}` and carry out the served action. Stop only at a human gate or "
        f"when the run is done.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
