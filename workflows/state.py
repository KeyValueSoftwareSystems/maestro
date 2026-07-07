#!/usr/bin/env python3
"""Per-step 'done' ledger for Conductor sub-workflows.

Ledger lives at <root>/<slug>/state.json (root defaults to .sdlc). Only script
steps in a workflow should call this — never an LLM/agent step.

Usage:
  python3 workflows/state.py check --slug S --step ID [--key K]
  python3 workflows/state.py mark  --slug S --step ID [--key K] --artifact PATH
  python3 workflows/state.py reset --slug S (--step ID [--step ID2 ...] | --all) [--key K]

Exit codes: check -> 0 done / 1 not-done; mark -> 0 marked / 1 artifact missing;
reset -> 0. See docs/superpowers/specs/2026-07-07-subworkflow-step-ledger-resume-design.md
"""
import json
import os
from pathlib import Path

DEFAULT_ROOT = Path(".sdlc")


def ledger_path(slug: str, root: Path = DEFAULT_ROOT) -> Path:
    return root / slug / "state.json"


def lock_path(slug: str, root: Path = DEFAULT_ROOT) -> Path:
    return root / slug / "state.json.lock"


def step_key(step: str, key: str | None = None) -> str:
    return f"{step}:{key}" if key else step


def _empty_ledger(slug: str) -> dict:
    return {"version": 1, "slug": slug, "steps": {}}


def load_ledger(slug: str, root: Path = DEFAULT_ROOT) -> dict:
    p = ledger_path(slug, root)
    if not p.is_file():
        return _empty_ledger(slug)
    with p.open() as f:
        return json.load(f)


def save_ledger(slug: str, data: dict, root: Path = DEFAULT_ROOT) -> None:
    p = ledger_path(slug, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, p)
