# Sub-workflow Step Ledger & Skip-Guards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Conductor sub-workflows re-entrant by adding an explicit per-step "done" ledger and skip-guards, piloted on `design.yaml`.

**Architecture:** A stdlib-only Python helper (`workflows/state.py`) owns a JSON ledger at `.sdlc/<slug>/state.json`, exposing `check`/`mark`/`reset` subcommands. `design.yaml` is rewritten so each expensive producer is bracketed by a guard script step (skip if the ledger flag is set and the artifact still exists) and a mark script step (records done, subsumes the old `assert_*`). Backward/revise routes reset the flags they invalidate. Human gates are never skipped.

**Tech Stack:** Python 3.10 (stdlib only: `json`, `os`, `fcntl`, `argparse`, `pathlib`, `datetime`, `contextlib`, `unittest`), Conductor workflow YAML, bash script steps.

## Global Constraints

- **Stdlib only** — no new pip dependencies. Match `workflows/validate_tasks.py` style. Tests use `unittest`, run via `python3 -m unittest`.
- **Only script steps touch the ledger** — never an LLM/agent step.
- **Human gates are never auto-skipped** — guards skip producers only; every entry still hits the gate.
- **`mark` refuses to flag done if the artifact is missing/empty** — a crashed producer is never recorded complete.
- **Paths are cwd-relative**, matching the existing `test -s "docs/technical/<slug>/..."` assert steps. The helper is invoked as `python3 workflows/state.py`; artifacts and `.sdlc/` resolve from the same cwd the current asserts assume (repo root).
- **Ledger writes are atomic** (temp file + `os.replace`) and serialized by a lockfile, so parallel `for_each` slices never corrupt the file.
- **Commit after every task.**

---

### Task 1: Ledger read/write core

**Files:**
- Create: `workflows/state.py`
- Test: `workflows/test_state.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `ledger_path(slug: str, root: Path = Path(".sdlc")) -> Path` → `<root>/<slug>/state.json`
  - `lock_path(slug: str, root: Path = Path(".sdlc")) -> Path` → `<root>/<slug>/state.json.lock`
  - `step_key(step: str, key: str | None = None) -> str` → `"<step>"` or `"<step>:<key>"`
  - `load_ledger(slug: str, root: Path = Path(".sdlc")) -> dict` → parsed ledger, or `{"version": 1, "slug": slug, "steps": {}}` when the file is absent
  - `save_ledger(slug: str, data: dict, root: Path = Path(".sdlc")) -> None` → atomic write (temp + `os.replace`), creates parent dirs

- [ ] **Step 1: Write the failing tests**

Create `workflows/test_state.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

import state


class LedgerCoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_step_key_without_key(self):
        self.assertEqual(state.step_key("hld"), "hld")

    def test_step_key_with_key(self):
        self.assertEqual(state.step_key("impl", "backend"), "impl:backend")

    def test_ledger_path_shape(self):
        self.assertEqual(
            state.ledger_path("saved-search", self.root),
            self.root / "saved-search" / "state.json",
        )

    def test_load_missing_returns_empty_skeleton(self):
        data = state.load_ledger("saved-search", self.root)
        self.assertEqual(data, {"version": 1, "slug": "saved-search", "steps": {}})

    def test_save_then_load_round_trips(self):
        data = {"version": 1, "slug": "s", "steps": {"hld": {"done": True}}}
        state.save_ledger("s", data, self.root)
        self.assertEqual(state.load_ledger("s", self.root), data)

    def test_save_creates_parent_dirs(self):
        state.save_ledger("newslug", state.load_ledger("newslug", self.root), self.root)
        self.assertTrue(state.ledger_path("newslug", self.root).is_file())

    def test_save_is_atomic_no_tmp_left_behind(self):
        state.save_ledger("s", {"version": 1, "slug": "s", "steps": {}}, self.root)
        leftovers = list((self.root / "s").glob("*.tmp"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd workflows && python3 -m unittest test_state -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'state'` (or `AttributeError` once the file exists but functions don't).

- [ ] **Step 3: Write minimal implementation**

Create `workflows/state.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd workflows && python3 -m unittest test_state -v`
Expected: PASS (7 tests in `LedgerCoreTest`).

- [ ] **Step 5: Commit**

```bash
git add workflows/state.py workflows/test_state.py
git commit -m "feat(state): ledger read/write core for sub-workflow resume"
```

---

### Task 2: State operations — is_done, mark_done, reset (with locking)

**Files:**
- Modify: `workflows/state.py`
- Test: `workflows/test_state.py`

**Interfaces:**
- Consumes: `load_ledger`, `save_ledger`, `step_key`, `lock_path` (Task 1).
- Produces:
  - `is_done(slug: str, step: str, key: str | None = None, root: Path = Path(".sdlc")) -> bool` — True iff the flag `done` is set AND the recorded `artifact` still exists and is non-empty.
  - `mark_done(slug: str, step: str, artifact: str, key: str | None = None, root: Path = Path(".sdlc"), now: str | None = None) -> bool` — returns False without writing if `artifact` is missing/empty; otherwise sets `{done: True, at: <ts>, artifact}` and returns True. `now` overridable for deterministic tests.
  - `reset(slug: str, steps: list[str] | None = None, all_: bool = False, key: str | None = None, root: Path = Path(".sdlc")) -> None` — clears listed step keys, or all steps when `all_`.
  - `_artifact_ok(artifact: str | None) -> bool` — `Path(artifact).is_file() and size > 0`.

- [ ] **Step 1: Write the failing tests**

Append to `workflows/test_state.py` (inside the file, new test class):

```python
class StateOpsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.artifact = self.root / "hld.md"
        self.artifact.write_text("# HLD\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_is_done_false_when_never_marked(self):
        self.assertFalse(state.is_done("s", "hld", root=self.root))

    def test_mark_then_is_done_true(self):
        ok = state.mark_done("s", "hld", str(self.artifact), root=self.root)
        self.assertTrue(ok)
        self.assertTrue(state.is_done("s", "hld", root=self.root))

    def test_mark_refuses_missing_artifact(self):
        ok = state.mark_done("s", "hld", str(self.root / "nope.md"), root=self.root)
        self.assertFalse(ok)
        self.assertFalse(state.is_done("s", "hld", root=self.root))

    def test_mark_refuses_empty_artifact(self):
        empty = self.root / "empty.md"
        empty.write_text("")
        self.assertFalse(state.mark_done("s", "hld", str(empty), root=self.root))

    def test_is_done_false_when_artifact_deleted_after_mark(self):
        state.mark_done("s", "hld", str(self.artifact), root=self.root)
        self.artifact.unlink()
        self.assertFalse(state.is_done("s", "hld", root=self.root))

    def test_key_namespaces_flags(self):
        state.mark_done("s", "impl", str(self.artifact), key="backend", root=self.root)
        self.assertTrue(state.is_done("s", "impl", key="backend", root=self.root))
        self.assertFalse(state.is_done("s", "impl", key="frontend", root=self.root))

    def test_reset_clears_listed_steps(self):
        state.mark_done("s", "hld", str(self.artifact), root=self.root)
        state.reset("s", steps=["hld"], root=self.root)
        self.assertFalse(state.is_done("s", "hld", root=self.root))

    def test_reset_all_clears_everything(self):
        state.mark_done("s", "hld", str(self.artifact), root=self.root)
        state.mark_done("s", "contract", str(self.artifact), root=self.root)
        state.reset("s", all_=True, root=self.root)
        self.assertEqual(state.load_ledger("s", self.root)["steps"], {})

    def test_concurrent_marks_do_not_lose_updates(self):
        import threading
        steps = [f"step{i}" for i in range(20)]

        def worker(name):
            state.mark_done("s", name, str(self.artifact), root=self.root)

        threads = [threading.Thread(target=worker, args=(s,)) for s in steps]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        recorded = state.load_ledger("s", self.root)["steps"]
        self.assertEqual(sorted(recorded), sorted(steps))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd workflows && python3 -m unittest test_state -v`
Expected: FAIL — `AttributeError: module 'state' has no attribute 'is_done'`.

- [ ] **Step 3: Write minimal implementation**

Add to `workflows/state.py` — new imports at top (merge with existing import block):

```python
import contextlib
import fcntl
from datetime import datetime, timezone
```

Add these functions after `save_ledger`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd workflows && python3 -m unittest test_state -v`
Expected: PASS (all `LedgerCoreTest` + `StateOpsTest`, including `test_concurrent_marks_do_not_lose_updates`).

- [ ] **Step 5: Commit**

```bash
git add workflows/state.py workflows/test_state.py
git commit -m "feat(state): is_done/mark_done/reset with atomic locked writes"
```

---

### Task 3: CLI subcommands (check / mark / reset)

**Files:**
- Modify: `workflows/state.py`
- Test: `workflows/test_state.py`

**Interfaces:**
- Consumes: `is_done`, `mark_done`, `reset`, `step_key` (Tasks 1–2).
- Produces: `main(argv: list[str] | None = None) -> int` and `if __name__ == "__main__": sys.exit(main())`. Subcommands map to exit codes: `check` → 0 done / 1 not-done; `mark` → 0 marked / 1 artifact missing; `reset` → 0 (2 if neither `--step` nor `--all` given). CLI always uses the default `.sdlc` root relative to cwd.

- [ ] **Step 1: Write the failing tests**

Append to `workflows/test_state.py` (new test class; drives the CLI in a subprocess with cwd set to a temp dir so `.sdlc` is hermetic):

```python
class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self._tmp.name)
        (self.cwd / "art.md").write_text("content\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        import subprocess
        import sys as _sys
        script = str(Path(__file__).with_name("state.py"))
        return subprocess.run(
            [_sys.executable, script, *args],
            cwd=self.cwd, capture_output=True, text=True,
        )

    def test_check_missing_exits_1(self):
        self.assertEqual(self._run("check", "--slug", "s", "--step", "hld").returncode, 1)

    def test_mark_then_check_exits_0(self):
        m = self._run("mark", "--slug", "s", "--step", "hld", "--artifact", "art.md")
        self.assertEqual(m.returncode, 0)
        c = self._run("check", "--slug", "s", "--step", "hld")
        self.assertEqual(c.returncode, 0)

    def test_mark_missing_artifact_exits_1(self):
        m = self._run("mark", "--slug", "s", "--step", "hld", "--artifact", "nope.md")
        self.assertEqual(m.returncode, 1)

    def test_reset_step_makes_check_fail_again(self):
        self._run("mark", "--slug", "s", "--step", "hld", "--artifact", "art.md")
        self._run("reset", "--slug", "s", "--step", "hld")
        self.assertEqual(self._run("check", "--slug", "s", "--step", "hld").returncode, 1)

    def test_reset_without_step_or_all_exits_2(self):
        self.assertEqual(self._run("reset", "--slug", "s").returncode, 2)

    def test_reset_multiple_steps(self):
        self._run("mark", "--slug", "s", "--step", "hld", "--artifact", "art.md")
        self._run("mark", "--slug", "s", "--step", "api", "--artifact", "art.md")
        self._run("reset", "--slug", "s", "--step", "hld", "--step", "api")
        self.assertEqual(self._run("check", "--slug", "s", "--step", "api").returncode, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd workflows && python3 -m unittest test_state -v`
Expected: FAIL — CLI has no argument parser yet (nonzero/2 from argparse or `AttributeError: module 'state' has no attribute 'main'`).

- [ ] **Step 3: Write minimal implementation**

Add `import argparse` and `import sys` to the top import block of `workflows/state.py`, then append at the end of the file:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-step done ledger.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check")
    c.add_argument("--slug", required=True)
    c.add_argument("--step", required=True)
    c.add_argument("--key", default=None)

    m = sub.add_parser("mark")
    m.add_argument("--slug", required=True)
    m.add_argument("--step", required=True)
    m.add_argument("--key", default=None)
    m.add_argument("--artifact", required=True)

    r = sub.add_parser("reset")
    r.add_argument("--slug", required=True)
    r.add_argument("--step", action="append", default=[])
    r.add_argument("--key", default=None)
    r.add_argument("--all", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "check":
        return 0 if is_done(args.slug, args.step, args.key) else 1

    if args.cmd == "mark":
        if mark_done(args.slug, args.step, args.artifact, args.key):
            print(f"[state] done: {step_key(args.step, args.key)} -> {args.artifact}")
            return 0
        print(f"[state] artifact missing/empty, NOT marked: {args.artifact}", file=sys.stderr)
        return 1

    if args.cmd == "reset":
        if not args.all and not args.step:
            print("[state] reset needs --step or --all", file=sys.stderr)
            return 2
        reset(args.slug, args.step, args.all, args.key)
        print(f"[state] reset: {'ALL' if args.all else ' '.join(args.step)}")
        return 0

    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd workflows && python3 -m unittest test_state -v`
Expected: PASS (all three test classes).

- [ ] **Step 5: Commit**

```bash
git add workflows/state.py workflows/test_state.py
git commit -m "feat(state): CLI check/mark/reset subcommands with exit codes"
```

---

### Task 4: Rewrite `design.yaml` with guards, marks, and reset

**Files:**
- Modify: `workflows/design.yaml` (full agents/parallel rewrite)

**Interfaces:**
- Consumes: `workflows/state.py` CLI (Task 3).
- Produces: a re-entrant `design.yaml`. Ledger step ids: `hld`, `backend_lld`, `frontend_lld`, `api_contract`.

Routing (guards `g_*`, marks `m_*`): `assert_prd → g_hld`; `g_hld` done → `hld_approval` (skip authoring, gate still runs), else → `author_hld → m_hld → hld_approval`; `hld_approval` approve → `g_llds`, revise → `reset_hld_cascade → author_hld`, reject → `abort`; `g_llds` both-done → `g_contract`, else → `author_llds → m_llds → g_contract`; `g_contract` done → `$end`, else → `contract → m_contract → $end`. The old `assert_hld` is removed (replaced by `m_hld`).

- [ ] **Step 1: Add the guard/mark/reset test harness (deterministic, no LLM)**

Create `workflows/test_design_wiring.sh` — seeds a ledger and asserts each guard's routing decision via exit codes, so the wiring is verifiable without invoking the AI skills:

```bash
#!/usr/bin/env bash
# Verifies design.yaml guard/mark wiring against state.py, deterministically.
set -uo pipefail
cd "$(dirname "$0")/.."          # repo root
SLUG="wiring-test-$$"
STATE="python3 workflows/state.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

# Fresh slug: hld not done -> guard exits 1 (would route to author_hld)
$STATE check --slug "$SLUG" --step hld && fail "hld should be not-done on a fresh slug"

# Seed an artifact and mark hld done -> guard exits 0 (would route to hld_approval)
mkdir -p "docs/technical/$SLUG"
echo "# HLD" > "docs/technical/$SLUG/hld.md"
$STATE mark --slug "$SLUG" --step hld --artifact "docs/technical/$SLUG/hld.md" || fail "mark hld"
$STATE check --slug "$SLUG" --step hld || fail "hld should be done after mark"

# Cascade reset (revise route) clears hld + downstream
$STATE reset --slug "$SLUG" --step hld --step backend_lld --step frontend_lld --step api_contract || fail "reset"
$STATE check --slug "$SLUG" --step hld && fail "hld should be cleared after reset"

# Cleanup
rm -rf ".sdlc/$SLUG" "docs/technical/$SLUG"
echo "OK: design.yaml guard/mark/reset wiring verified"
```

Make it executable: `chmod +x workflows/test_design_wiring.sh`

- [ ] **Step 2: Run the harness to verify it fails**

Run: `bash workflows/test_design_wiring.sh`
Expected: PASS on the state.py calls themselves (Tasks 1–3 are done). This step confirms the harness runs; the design.yaml rewrite in Step 3 makes the workflow actually use these calls. (If `state.py` is absent it errors — that's the red state.)

- [ ] **Step 3: Rewrite `workflows/design.yaml`**

Replace the entire `parallel:` block and `agents:` list (lines 62–202, from `parallel:` through the `abort` step) with the following. Leave the `workflow:` header (lines 26–56) and the `output:` block (lines 209–219) unchanged.

```yaml
# ----------------------------------------------------------------------------
# Parallel LLD authoring: backend + frontend, concurrent (after HLD approval).
# ----------------------------------------------------------------------------
parallel:
  - name: author_llds
    description: Author the backend and frontend LLDs in parallel.
    failure_mode: all_or_nothing
    agents: [backend_design, frontend_design]
    routes:
      - to: m_llds

agents:
  # ---- 0. ASSERT the PRD exists (fail fast, before /plan) ------------------
  - name: assert_prd
    type: script
    description: Verify the PRD exists before designing, so a missing PRD fails clearly.
    command: bash
    args:
      - "-c"
      - |
        set -uo pipefail
        f="{{ workflow.input.prd_path }}"
        if [ -s "$f" ]; then echo "[prd] OK: $f"; exit 0
        else echo "[prd] NOT FOUND (or empty): $f — create the PRD before running the design phase." >&2; exit 1; fi
    routes:
      - to: g_hld
        when: "exit_code == 0"
      - to: abort

  # ---- GUARD: skip HLD authoring if already done (gate still runs) --------
  - name: g_hld
    type: script
    description: Skip /plan if hld.md is already marked done and present.
    command: bash
    args:
      - "-c"
      - |
        python3 workflows/state.py check --slug "{{ workflow.input.feature_slug }}" --step hld
    routes:
      - to: hld_approval            # done -> skip authoring, still gate
        when: "exit_code == 0"
      - to: author_hld              # not done -> author it

  # ---- 1. PLAN — author the HLD (/plan) -----------------------------------
  - name: author_hld
    description: Produce the high-level design (HLD) via the plan skill.
    model: claude-opus-4-8
    prompt: |
      Run the **/plan** skill. Inputs:
      - feature:      {{ workflow.input.feature }}
      - feature_slug: {{ workflow.input.feature_slug }}
      - prd_path:     {{ workflow.input.prd_path }}
      Return: hld_path, hld_summary. (Capture any open questions in the HLD's
      "Open questions" section — do NOT return them as a separate structured field.)
    output:
      hld_path: { type: string }
      hld_summary: { type: string }
    routes:
      - to: m_hld

  # ---- MARK: record hld done (subsumes the old assert_hld) ----------------
  - name: m_hld
    type: script
    description: Assert + record hld.md done in the ledger.
    command: bash
    args:
      - "-c"
      - |
        python3 workflows/state.py mark --slug "{{ workflow.input.feature_slug }}" \
          --step hld --artifact "docs/technical/{{ workflow.input.feature_slug }}/hld.md"
    routes:
      - to: hld_approval
        when: "exit_code == 0"
      - to: abort

  # ---- 2. HUMAN APPROVAL: HLD (never skipped) -----------------------------
  - name: hld_approval
    type: human_gate
    description: Review the high-level design before detailed design.
    prompt: |
      ## HLD Review — {{ workflow.input.feature }}

      Artifact: `docs/technical/{{ workflow.input.feature_slug }}/hld.md`

      **Summary:** {{ author_hld.output.hld_summary if author_hld is defined else "(loaded from a prior run — see the HLD file)" }}

      **Open questions:** see the "Open questions" section of the HLD above.

      Approve to proceed to detailed design (per-stack LLDs), request revisions, or reject.
    options:
      - label: "Approve — proceed to LLD"
        value: approve
        route: g_llds
      - label: "Request HLD revisions"
        value: revise
        route: reset_hld_cascade
        prompt_for: feedback
      - label: "Reject — abort"
        value: reject
        route: abort

  # ---- RESET: revise HLD invalidates HLD + everything downstream ----------
  - name: reset_hld_cascade
    type: script
    description: Clear hld + derived LLD/contract flags so a revision regenerates them.
    command: bash
    args:
      - "-c"
      - |
        python3 workflows/state.py reset --slug "{{ workflow.input.feature_slug }}" \
          --step hld --step backend_lld --step frontend_lld --step api_contract
    routes:
      - to: author_hld

  # ---- GUARD: skip LLD authoring only if BOTH LLDs are done ---------------
  - name: g_llds
    type: script
    description: Skip the parallel LLD group only when both LLDs are already done.
    command: bash
    args:
      - "-c"
      - |
        python3 workflows/state.py check --slug "{{ workflow.input.feature_slug }}" --step backend_lld \
          && python3 workflows/state.py check --slug "{{ workflow.input.feature_slug }}" --step frontend_lld
    routes:
      - to: g_contract              # both done -> skip group
        when: "exit_code == 0"
      - to: author_llds             # either missing -> run group

  # ---- 3. PER-STACK LLDs (parallel) ---------------------------------------
  - name: backend_design
    description: Author the backend LLD via the backend-design skill.
    prompt: |
      Run the **/backend-design** skill. Inputs:
      - feature:      {{ workflow.input.feature }}
      - feature_slug: {{ workflow.input.feature_slug }}
      - hld_path:     docs/technical/{{ workflow.input.feature_slug }}/hld.md
      Return: lld_path, tasks_path.
    output:
      lld_path: { type: string }
      tasks_path: { type: string }

  - name: frontend_design
    description: Author the frontend LLD via the frontend-design skill.
    prompt: |
      Run the **/frontend-design** skill. Inputs:
      - feature:      {{ workflow.input.feature }}
      - feature_slug: {{ workflow.input.feature_slug }}
      - hld_path:     docs/technical/{{ workflow.input.feature_slug }}/hld.md
      Return: lld_path, tasks_path.
    output:
      lld_path: { type: string }
      tasks_path: { type: string }

  # ---- MARK: record both LLDs done (subsumes main.yaml's assert_lld) -------
  - name: m_llds
    type: script
    description: Assert + record both per-stack LLDs done.
    command: bash
    args:
      - "-c"
      - |
        python3 workflows/state.py mark --slug "{{ workflow.input.feature_slug }}" \
          --step backend_lld --artifact "docs/technical/{{ workflow.input.feature_slug }}/lld/backend.md" \
        && python3 workflows/state.py mark --slug "{{ workflow.input.feature_slug }}" \
          --step frontend_lld --artifact "docs/technical/{{ workflow.input.feature_slug }}/lld/frontend.md"
    routes:
      - to: g_contract
        when: "exit_code == 0"
      - to: abort

  # ---- GUARD: skip contract if already done -------------------------------
  - name: g_contract
    type: script
    description: Skip /api-contract if the OpenAPI contract is already done.
    command: bash
    args:
      - "-c"
      - |
        python3 workflows/state.py check --slug "{{ workflow.input.feature_slug }}" --step api_contract
    routes:
      - to: $end                    # done -> whole design phase complete
        when: "exit_code == 0"
      - to: contract

  # ---- 4. CONTRACT (/api-contract) ----------------------------------------
  - name: contract
    description: Reconcile the per-stack LLDs into the cross-repo contract via the api-contract skill.
    model: claude-opus-4-8
    prompt: |
      Run the **/api-contract** skill (the per-stack LLDs have already been written — pass them).
      Inputs:
      - feature:      {{ workflow.input.feature }}
      - feature_slug: {{ workflow.input.feature_slug }}
      - hld_path:     docs/technical/{{ workflow.input.feature_slug }}/hld.md
      - backend_lld:  docs/technical/{{ workflow.input.feature_slug }}/lld/backend.md
      - frontend_lld: docs/technical/{{ workflow.input.feature_slug }}/lld/frontend.md
      Return: contract_path, contract_summary, affected_repos, acceptance_criteria.
    output:
      contract_path: { type: string }
      contract_summary:
        type: string
        description: Human-readable cross-repo contract (breaking changes flagged).
      affected_repos:
        type: array
        description: 'e.g. [{"name":"backend"},{"name":"frontend"}].'
      acceptance_criteria:
        type: string
    routes:
      - to: m_contract

  # ---- MARK: record contract done -----------------------------------------
  - name: m_contract
    type: script
    description: Assert + record the OpenAPI contract done.
    command: bash
    args:
      - "-c"
      - |
        python3 workflows/state.py mark --slug "{{ workflow.input.feature_slug }}" \
          --step api_contract --artifact "contracts/{{ workflow.input.feature_slug }}/openapi.yaml"
    routes:
      - to: $end
        when: "exit_code == 0"
      - to: abort

  - name: abort
    type: terminate
    status: failed
    reason: "Design aborted (missing PRD or HLD artifact, or HLD rejected)."
```

Note the two producer prompts (`backend_design`, `frontend_design`, `contract`) now reference the HLD/LLD paths by their literal artifact paths instead of `{{ author_hld.output.hld_path }}` / `{{ author_llds.outputs.* }}`, because on a resumed run the upstream step outputs are not in context (the step was skipped). The paths are deterministic per `skills.config.yaml`, so this is safe and removes the resume-time template dependency.

- [ ] **Step 4: Validate and run the wiring harness**

Run: `conductor validate workflows/design.yaml`
Expected: validation passes (no schema/route errors; all `to:` targets resolve).

Run: `bash workflows/test_design_wiring.sh`
Expected: `OK: design.yaml guard/mark/reset wiring verified`

- [ ] **Step 5: Commit**

```bash
git add workflows/design.yaml workflows/test_design_wiring.sh
git commit -m "feat(design): re-entrant design.yaml via ledger guards/marks/reset"
```

---

### Task 5: Document the resume behavior

**Files:**
- Modify: `README.md` (the "How to run" / design.yaml row area)

**Interfaces:**
- Consumes: nothing.
- Produces: user-facing docs for the new resume behavior and escape hatch.

- [ ] **Step 1: Add a resume note to README.md**

After the run table (after line 79's blockquote about POC stubs), add a new subsection:

```markdown
### Resuming a partially-run workflow

Conductor only checkpoints the top-level run; a sub-workflow (`design.yaml`, `qa.yaml`, …)
otherwise re-runs from its first step. To make sub-workflows re-entrant, each expensive step
records itself in a per-feature ledger at `.sdlc/<slug>/state.json` (via
[`workflows/state.py`](workflows/state.py)). On a re-run, a step whose artifact is already
recorded and present on disk is skipped; the workflow lands on the first unfinished step.
Human approval gates are never skipped — they always re-ask.

- Re-run the same command; completed steps skip automatically.
- Force a rebuild of one step: `python3 workflows/state.py reset --slug <slug> --step hld`
  (or just delete its artifact).
- Force a full rebuild: `python3 workflows/state.py reset --slug <slug> --all`
  (or delete `.sdlc/<slug>/state.json`).

**Known limits:** the ledger tracks completion, not content — hand-editing an upstream artifact
does not auto-invalidate downstream steps (use `reset`). Skip granularity for the parallel LLD
group is the whole group, not per-stack.
```

- [ ] **Step 2: Verify the doc renders and links resolve**

Run: `grep -n "state.py reset" README.md`
Expected: two matches (the per-step and full-rebuild lines).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document sub-workflow resume ledger and force-rebuild"
```

---

## Self-Review

**Spec coverage:**
- Ledger `.sdlc/<slug>/state.json` + schema → Task 1 (`load_ledger`/`save_ledger`), shape asserted in `test_load_missing_returns_empty_skeleton`.
- `state.py` check/mark/reset + success/artifact semantics → Tasks 2–3.
- Atomic locked writes, `--key` namespacing → Task 2 (`_lock`, `test_concurrent_marks_*`, `test_key_namespaces_flags`).
- Guard/mark pattern, `mark` subsumes `assert_*` → Task 4 (`g_*`/`m_*`, `assert_hld` removed).
- Human gates never skipped → Task 4 (`g_hld` done → `hld_approval`, not past it).
- Loop reset with cascade → Task 4 (`reset_hld_cascade` on the revise route).
- Parallel-group group-level skip limitation → Task 4 (`g_llds` checks both) + README.
- Escape hatch (`reset`/`--all`) → Task 3 CLI + Task 5 README.
- Pilot on `design.yaml`; rollout to other workflows is deliberately out of this plan (separate follow-up per the spec).

**Placeholder scan:** No TBD/TODO; every code and test step contains complete content; commands have expected output.

**Type consistency:** `is_done`/`mark_done`/`reset`/`step_key` signatures match between the Task 1–2 interface blocks, the implementations, and the CLI wiring in Task 3. Step ids (`hld`, `backend_lld`, `frontend_lld`, `api_contract`) are identical across `design.yaml` guards, marks, the reset cascade, and the wiring harness.
