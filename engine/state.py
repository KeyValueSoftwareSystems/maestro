"""Per-feature run ledger: .maestro/<slug>/state.yaml.

Only engine code writes this file — the lead agent never edits it (LLMs corrupt
hand-edited state). Writes go through an fcntl lock plus tmp+rename, both carried over
from the v1 workflows/state.py. A corrupt ledger fails soft: treated as absent, with a
warning on stderr, so a damaged file never bricks a run.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import os
import re
import sys

try:
    import wf
except ImportError:  # imported as part of a package (tests)
    from . import wf

# Cross-platform advisory file lock. POSIX uses fcntl; Windows uses msvcrt; if neither is
# available locking degrades to a no-op with a one-time warning (single-user runs are still
# safe — the risk is only two concurrent writers on the same slug).
try:
    import fcntl

    def _lock_fh(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _unlock_fh(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    _LOCKING = "fcntl"
except ImportError:  # pragma: no cover - platform-specific
    try:
        import msvcrt

        def _lock_fh(fh):
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)

        def _unlock_fh(fh):
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass

        _LOCKING = "msvcrt"
    except ImportError:
        def _lock_fh(fh):
            pass

        def _unlock_fh(fh):
            pass

        _LOCKING = None

_LOCK_WARNED = False

MAESTRO_DIR = ".maestro"
STATE_VERSION = 1

# A slug becomes a directory name under .maestro/; keep it a single safe path segment so a
# stray `/` or `..` can never scatter state outside the feature folder.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def valid_slug(slug):
    return bool(isinstance(slug, str) and _SLUG_RE.match(slug) and ".." not in slug)


def feature_dir(slug, root="."):
    return os.path.join(root, MAESTRO_DIR, slug)


def state_path(slug, root="."):
    return os.path.join(feature_dir(slug, root), "state.yaml")


def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_ok(path, root="."):
    full = path if os.path.isabs(path) else os.path.join(root, path)
    try:
        return os.path.getsize(full) > 0
    except OSError:
        return False


def new_state(slug, workflow_file, workflow_hash, inputs):
    return {
        "version": STATE_VERSION,
        "slug": slug,
        "workflow": {"file": workflow_file, "sha256": workflow_hash},
        "frames": {},  # path -> {workflow, sha256, inputs} for entered subworkflows
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "inputs": inputs,
        "run": {"status": "running", "cursors": []},
        "steps": {},
        "gates": [],
    }


def step_entry(state, path):
    entry = state["steps"].get(path)
    if entry is None:
        entry = {"status": "pending", "attempts": 0, "visits": 0, "outputs": {}}
        state["steps"][path] = entry
    return entry


def load(slug, root="."):
    """Read-only load. Returns None if absent; corrupt files fail soft to None."""
    path = state_path(slug, root)
    if not os.path.exists(path):
        return None
    try:
        data = wf.load_file(path)
    except (OSError, ValueError) as exc:
        # ValueError covers wf.WfError and UnicodeDecodeError (non-UTF-8 / binary junk).
        print(f"warning: corrupt state file {path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        print(f"warning: unsupported state file {path}; ignoring it", file=sys.stderr)
        return None
    return data


def save(slug, state, root="."):
    state["updated_at"] = now_iso()
    path = state_path(slug, root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wf.dump_file(path, state)


@contextlib.contextmanager
def locked(slug, root="."):
    """Exclusive lock around a read-modify-write of the ledger."""
    global _LOCK_WARNED
    if _LOCKING is None and not _LOCK_WARNED:
        print("warning: no file locking on this platform — do not run two maestro "
              "commands on the same slug at once", file=sys.stderr)
        _LOCK_WARNED = True
    directory = feature_dir(slug, root)
    os.makedirs(directory, exist_ok=True)
    lock_file = os.path.join(directory, "state.yaml.lock")
    fh = open(lock_file, "a+")
    try:
        _lock_fh(fh)
        yield
    finally:
        _unlock_fh(fh)
        fh.close()
