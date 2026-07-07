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
import contextlib
import fcntl
import json
import os
from datetime import datetime, timezone
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


def _artifact_ok(artifact: str | None) -> bool:
    if not artifact:
        return False
    p = Path(artifact)
    return p.is_file() and p.stat().st_size > 0


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextlib.contextmanager
def _lock(slug: str, root: Path = DEFAULT_ROOT):
    lp = lock_path(slug, root)
    lp.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lp), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def is_done(slug: str, step: str, key: str | None = None, root: Path = DEFAULT_ROOT) -> bool:
    entry = load_ledger(slug, root)["steps"].get(step_key(step, key))
    if not entry or not entry.get("done"):
        return False
    return _artifact_ok(entry.get("artifact"))


def mark_done(
    slug: str,
    step: str,
    artifact: str,
    key: str | None = None,
    root: Path = DEFAULT_ROOT,
    now: str | None = None,
) -> bool:
    if not _artifact_ok(artifact):
        return False
    with _lock(slug, root):
        data = load_ledger(slug, root)
        data["steps"][step_key(step, key)] = {
            "done": True,
            "at": now or _utcnow(),
            "artifact": artifact,
        }
        save_ledger(slug, data, root)
    return True


def reset(
    slug: str,
    steps: list[str] | None = None,
    all_: bool = False,
    key: str | None = None,
    root: Path = DEFAULT_ROOT,
) -> None:
    with _lock(slug, root):
        data = load_ledger(slug, root)
        if all_:
            data["steps"] = {}
        else:
            for s in steps or []:
                data["steps"].pop(step_key(s, key), None)
        save_ledger(slug, data, root)
