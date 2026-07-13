"""Read-only engine-side helpers for the .maestro/memory knowledge store.

The engine ONLY reads the knowledge tier, and only once — at init, to freeze a per-run
snapshot (see resolver.init_run). Every WRITE to the store (bootstrap, retrospect,
consolidate) is done by LLM skills, never here. The snapshot is JSON (not the YAML subset)
so arbitrary markdown lesson text round-trips without any escaping surprises.
"""

from __future__ import annotations

import json
import os

try:
    import state as statemod
except ImportError:  # imported as a package (tests)
    from . import state as statemod

MEMORY_DIRNAME = "memory"


def knowledge_dir(root="."):
    return os.path.join(root, statemod.MAESTRO_DIR, MEMORY_DIRNAME, "knowledge")


def read_knowledge(root="."):
    """Return {domain_stem: file_text} for every *.md under knowledge/ (empty if absent)."""
    kd = knowledge_dir(root)
    out = {}
    if not os.path.isdir(kd):
        return out
    for name in sorted(os.listdir(kd)):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(kd, name), encoding="utf-8") as fh:
                out[name[:-3]] = fh.read()
        except OSError:
            continue
    return out


def snapshot_path(slug, root="."):
    return os.path.join(statemod.feature_dir(slug, root), "memory-snapshot.json")


def write_snapshot(slug, root, knowledge):
    """Freeze `knowledge` into the run's snapshot file. Atomic tmp+rename."""
    path = snapshot_path(slug, root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"knowledge": knowledge}, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return path


def load_snapshot(slug, root="."):
    """Read the frozen snapshot back. Empty dict if absent or unreadable."""
    path = snapshot_path(slug, root)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    return (doc or {}).get("knowledge", {}) or {}
