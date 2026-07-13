# Maestro Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Maestro a file-based, human-readable memory that is bootstrapped from the codebase, injected (frozen at init) into feature runs, and grown after each run via a retrospect→consolidate cycle that only promotes a lesson into trusted knowledge once ≥3 distinct runs corroborate it.

**Architecture:** A three-tier store under `.maestro/memory/` (`incoming/` per-run drops → `candidates/` accruing evidence → `knowledge/` promoted+injected). The engine gains one read primitive — a `${memory.knowledge.<domain>}` placeholder resolved from a per-run snapshot frozen at `init` — plus nested-placeholder support so per-stack keys work. All writing (bootstrap, retrospect, consolidate) is done by LLM skills driven by three new workflows, not by engine code. The pre-merge `archive` phase of `sdlc-main.yaml` runs the harvest by default.

**Tech Stack:** Python 3.8+ stdlib only (no dependencies, ever). YAML-subset workflows (`engine/wf.py`). Markdown skills with YAML frontmatter. `unittest` test suite.

## Global Constraints

- **Stdlib only.** No third-party imports anywhere in `engine/`.
- **Determinism / freeze-at-init.** Memory is read once at `init`, snapshotted, and resolved from the snapshot for the whole run. Never re-read the live store mid-run.
- **Engine never writes memory content.** The engine only READS `knowledge/` (once, at init). Bootstrap/retrospect/consolidate are LLM skills.
- **Skills own *how*, workflow nodes own paths.** New skills must not hardcode the store layout in a way that couples them to a pipeline position; the concrete `.maestro/memory/...` paths live in the workflow node `instruction`/`inputs`, injected at runtime.
- **Promotion threshold = 3 distinct runs** (default; overridable via `config.memory.promote_threshold`, read by the consolidate skill — not the engine).
- **Contract rule.** Every workflow agent-node `outputs:` field must appear in its pinned skill's `## Output contract` (`testdata/test_workflow_skill_contracts.py`).
- **After editing schema or workflows:** run `python3 ui/embed.py`, then keep `python3 testdata/test_ui_schema_sync.py` green.
- **Full suite must stay green:** `python3 engine/tests/run_all.py`.
- **Commits:** conventional messages, end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

**New engine module**
- `engine/memory.py` — read `knowledge/`, write/load the per-run snapshot. The only engine-side memory code.

**Engine edits**
- `engine/resolver.py` — `${memory.*}` resolution, freeze-at-init, nested placeholder resolution.
- `engine/state.py` — `memory` key in `new_state`.
- `engine/validate.py` — accept the `memory` namespace; innermost placeholder regex.

**New tests**
- `engine/tests/test_memory.py` — the store module.
- `engine/tests/test_resolver.py` — memory injection, nesting, freeze (append a class).
- `engine/tests/test_validate.py` — memory placeholder accept/reject (append).
- `engine/tests/test_sdlc_e2e.py` — drive the new archival subworkflow (edit canned table).

**New skills**
- `skills/build-knowledge/SKILL.md`, `skills/retrospect/SKILL.md`, `skills/consolidate-memory/SKILL.md`.

**New workflows**
- `workflows/build-knowledge.yaml`, `workflows/retrospect.yaml`, `workflows/archive.yaml`.

**Edits**
- `workflows/sdlc-main.yaml` — `archive` node → subworkflow; `arch_review` gains a memory input.
- `workflows/design.yaml` — `author_hld`/`backend_design`/`frontend_design` gain memory inputs.
- `workflows/impl.yaml` — `review` gains a nested memory input.
- `skills/{plan,backend-design,frontend-design,backend-review,frontend-review,architecture-review}/SKILL.md` — add a `## Prior lessons` section.
- Docs: `docs/workflow-spec.md`, `CLAUDE.md`, `README.md`, `docs/memory.md` (new), `docs/umbrella-workspace.md`.

---

## Task 1: Memory store module (`engine/memory.py`)

**Files:**
- Create: `engine/memory.py`
- Test: `engine/tests/test_memory.py`

**Interfaces:**
- Produces:
  - `read_knowledge(root=".") -> dict[str, str]` — `{domain_stem: file_text}` for every `*.md` under `.maestro/memory/knowledge/` (empty dict if the dir is absent).
  - `snapshot_path(slug, root=".") -> str`
  - `write_snapshot(slug, root, knowledge: dict) -> str` — writes `<feature_dir>/memory-snapshot.json`, returns its path.
  - `load_snapshot(slug, root=".") -> dict[str, str]` — reads it back (empty dict if absent/corrupt).

- [ ] **Step 1: Write the failing test**

Create `engine/tests/test_memory.py`:

```python
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import memory  # noqa: E402


class MemoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-mem-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def kdir(self):
        d = os.path.join(self.tmp, ".maestro", "memory", "knowledge")
        os.makedirs(d, exist_ok=True)
        return d

    def test_read_knowledge_empty_when_absent(self):
        self.assertEqual(memory.read_knowledge(self.tmp), {})

    def test_read_knowledge_reads_only_md(self):
        d = self.kdir()
        open(os.path.join(d, "codebase.md"), "w").write("line1\nline2\n")
        open(os.path.join(d, "plan.md"), "w").write("plan lesson")
        open(os.path.join(d, "ignore.txt"), "w").write("nope")
        k = memory.read_knowledge(self.tmp)
        self.assertEqual(set(k), {"codebase", "plan"})
        self.assertEqual(k["codebase"], "line1\nline2\n")

    def test_snapshot_roundtrip_multiline(self):
        data = {"codebase": "multi\nline\n# md **bold** ${notaref}\n", "plan": "x"}
        memory.write_snapshot("feat", self.tmp, data)
        self.assertEqual(memory.load_snapshot("feat", self.tmp), data)

    def test_load_snapshot_empty_when_absent(self):
        self.assertEqual(memory.load_snapshot("nope", self.tmp), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 engine/tests/test_memory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memory'`.

- [ ] **Step 3: Write the module**

Create `engine/memory.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 engine/tests/test_memory.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/memory.py engine/tests/test_memory.py
git commit -m "$(printf 'feat(engine): memory store module — read knowledge, freeze/load snapshot\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 2: Nested placeholder resolution (`resolver.py`)

Innermost-match + bounded iterative substitution, so `${a.${b}}` resolves inner-first. Behavior-preserving for every current placeholder (none contain `{`/`}` inside).

**Files:**
- Modify: `engine/resolver.py` (`_PLACEHOLDER_RE` ~line 55; `resolve_text` ~lines 166-177)
- Test: `engine/tests/test_resolver.py` (append a test)

**Interfaces:**
- Produces: `Run.resolve_text` now resolves nested placeholders (unchanged signature).

- [ ] **Step 1: Write the failing test** — append to `engine/tests/test_resolver.py`:

```python
class NestedPlaceholderTest(Sim):
    NESTED_WF = """\
version: 1
name: nested
inputs:
  slug: {type: string, required: true}
  stack: {type: string, default: backend}
start: work
nodes:
  - id: work
    type: agent
    instruction: "flat=${inputs.stack} nested=[${inputs.stack}-review]"
    outputs: [note]
    artifact: ".maestro/${inputs.slug}/work.md"
    next: end
"""

    def test_flat_placeholder_unchanged(self):
        self.start(self.write_wf("n.yaml", self.NESTED_WF))
        prompt = self.nxt()["prompt"]
        self.assertIn("flat=backend", prompt)
        self.assertIn("nested=[backend-review]", prompt)

    def test_bounded_loop_terminates(self):
        # A resolved value that itself looks like a placeholder must not hang; the pass
        # cap bounds it. steps refs resolve missing_ok -> empty here.
        run = self.run_obj_after_start()
        frame = run.main_frame()
        # ${inputs.stack} -> backend; no infinite loop
        self.assertEqual(run.resolve_text("${inputs.stack}", frame), "backend")

    def run_obj_after_start(self):
        self.start(self.write_wf("n.yaml", self.NESTED_WF))
        return self.run_obj()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 engine/tests/test_resolver.py NestedPlaceholderTest -v`
Expected: The real nested-memory case (Task 3) isn't in yet, but `test_flat_placeholder_unchanged` should already PASS (flat refs) and confirms no regression. To see the loop machinery is needed, note the current single-pass code cannot resolve `${a.${b}}`; Task 3's memory test is the true nested proof. Run this class now to confirm flat behavior is preserved after the edit.

- [ ] **Step 3: Make the edit**

In `engine/resolver.py`, change the regex (currently `_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")`) and add a cap constant:

```python
_PLACEHOLDER_RE = re.compile(r"\$\{([^{}]+)\}")
_MAX_SUBST_PASSES = 5
```

Replace `resolve_text` (currently a single `.sub`) with the bounded loop:

```python
    def resolve_text(self, text, frame, missing_ok=False):
        def repl(m):
            value = self.resolve_ref(m.group(1).strip(), frame, missing_ok)
            if value is None:
                return ""
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, (list, dict)):
                return json.dumps(value)
            return str(value)

        text = str(text)
        # Innermost-first regex + bounded loop resolves nested placeholders
        # (e.g. ${memory.knowledge.${inputs.stack}-review}) inside-out. The cap prevents a
        # value that itself contains ${...} from looping forever.
        for _ in range(_MAX_SUBST_PASSES):
            new = _PLACEHOLDER_RE.sub(repl, text)
            if new == text:
                break
            text = new
        return text
```

- [ ] **Step 4: Run tests**

Run: `python3 engine/tests/test_resolver.py NestedPlaceholderTest -v`
Expected: PASS. Then run the whole resolver suite for no regression:
Run: `python3 engine/tests/test_resolver.py -v`
Expected: PASS (all existing tests still green).

- [ ] **Step 5: Commit**

```bash
git add engine/resolver.py engine/tests/test_resolver.py
git commit -m "$(printf 'feat(engine): nested placeholder resolution (innermost-first, bounded)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 3: `${memory.*}` resolution + freeze-at-init (`resolver.py`, `state.py`)

**Files:**
- Modify: `engine/resolver.py` (imports ~lines 20-26; `Run.__init__` ~line 93; `resolve_ref` ~lines 179-208; `init_run` ~line 339)
- Modify: `engine/state.py` (`new_state` ~lines 103-115)
- Test: `engine/tests/test_resolver.py` (append a class)

**Interfaces:**
- Consumes: `memory.read_knowledge`, `memory.write_snapshot`, `memory.load_snapshot` (Task 1).
- Produces: `${memory.knowledge.<domain>}` resolves to the frozen snapshot's text for `<domain>` (empty string when absent, in the lenient paths). `state["memory"] = {"snapshot": <basename>, "sha256": <hash>}` recorded at init.

- [ ] **Step 1: Write the failing test** — append to `engine/tests/test_resolver.py`:

```python
class MemoryInjectionTest(Sim):
    MEM_WF = """\
version: 1
name: mem
inputs:
  slug: {type: string, required: true}
  stack: {type: string, default: backend}
start: work
nodes:
  - id: work
    type: agent
    instruction: Do the ${inputs.stack} work.
    inputs:
      general: "${memory.knowledge.codebase}"
      scoped: "${memory.knowledge.${inputs.stack}-review}"
      absent: "${memory.knowledge.nope}"
    outputs: [note]
    artifact: ".maestro/${inputs.slug}/work.md"
    next: end
"""

    def seed(self, domain, text):
        d = os.path.join(self.tmp, ".maestro", "memory", "knowledge")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, domain + ".md"), "w") as fh:
            fh.write(text)

    def test_injected_shared_nested_and_absent(self):
        self.seed("codebase", "SHARED-LESSON")
        self.seed("backend-review", "BE-REVIEW-LESSON")
        self.start(self.write_wf("m.yaml", self.MEM_WF))
        action = self.nxt()
        self.assertEqual(action["action"], "run_agent")
        prompt = action["prompt"]
        self.assertIn("SHARED-LESSON", prompt)          # ${memory.knowledge.codebase}
        self.assertIn("BE-REVIEW-LESSON", prompt)       # nested per-stack key
        self.assertNotIn("${memory", prompt)            # no leftover placeholder
        self.assertIn("absent:", prompt)                # absent domain -> blank value

    def test_frozen_at_init(self):
        self.seed("codebase", "ORIGINAL")
        self.start(self.write_wf("m.yaml", self.MEM_WF))
        self.seed("codebase", "CHANGED-AFTER-INIT")     # mutate the live store post-init
        prompt = self.nxt()["prompt"]
        self.assertIn("ORIGINAL", prompt)
        self.assertNotIn("CHANGED-AFTER-INIT", prompt)

    def test_snapshot_recorded_in_state(self):
        self.seed("codebase", "X")
        self.start(self.write_wf("m.yaml", self.MEM_WF))
        st = self.state()
        self.assertEqual(st["memory"]["snapshot"], "memory-snapshot.json")
        self.assertTrue(st["memory"]["sha256"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 engine/tests/test_resolver.py MemoryInjectionTest -v`
Expected: FAIL — `${memory...}` currently renders empty / raises, and `state["memory"]` is missing.

- [ ] **Step 3a: Import the memory module** — in `engine/resolver.py` update the import block:

```python
try:
    import condctl
    import memory as memorymod
    import state as statemod
    import validate as validatemod
    import wf
except ImportError:  # imported as a package (tests)
    from . import condctl, memory as memorymod, state as statemod, validate as validatemod, wf
```

- [ ] **Step 3b: Add the memory cache to `Run.__init__`** — after `self._wf_cache = {}` add:

```python
        self._memory_cache = None
```

- [ ] **Step 3c: Add the resolver branch + helper.** In `resolve_ref`, add this branch immediately after the `config` block (before the final `raise KeyError(ref)`):

```python
            if parts[0] == "memory" and len(parts) == 3 and parts[1] == "knowledge":
                return self._memory_knowledge()[parts[2]]
```

Add this method to `Run` (e.g. right after `_lookup_step`):

```python
    def _memory_knowledge(self):
        """The frozen memory snapshot for this run (loaded once, cached)."""
        if self._memory_cache is None:
            self._memory_cache = memorymod.load_snapshot(self.slug, self.root)
        return self._memory_cache
```

- [ ] **Step 3d: Freeze the snapshot at init.** In `init_run`, right after `data = statemod.new_state(slug, workflow_file, digest, resolved)` and BEFORE `run = Run(slug, root, state_data=data)`, insert:

```python
    # Freeze the memory knowledge snapshot for this run — read ONCE here, never re-read
    # live (keeps the run reproducible and immune to concurrent consolidation elsewhere).
    snap_path = memorymod.write_snapshot(slug, root, memorymod.read_knowledge(root))
    data["memory"] = {
        "snapshot": os.path.basename(snap_path),
        "sha256": statemod.sha256_file(snap_path),
    }
```

- [ ] **Step 3e: Add the `memory` key to `new_state`.** In `engine/state.py`, in `new_state`, add `"memory": {},` after the `"frames": {},` line:

```python
        "frames": {},  # path -> {workflow, sha256, inputs} for entered subworkflows
        "memory": {},  # {snapshot, sha256} — the frozen knowledge snapshot for this run
```

- [ ] **Step 4: Run tests**

Run: `python3 engine/tests/test_resolver.py MemoryInjectionTest -v`
Expected: PASS (3 tests).
Run: `python3 engine/tests/test_resolver.py -v` and `python3 engine/tests/test_state.py -v`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add engine/resolver.py engine/state.py engine/tests/test_resolver.py
git commit -m "$(printf 'feat(engine): %s{memory.knowledge.*} resolution frozen at init\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>' '$')"
```

---

## Task 4: Validator accepts the `memory` namespace (`validate.py`)

**Files:**
- Modify: `engine/validate.py` (`_PLACEHOLDER_RE` line 38; placeholder check ~lines 311-323)
- Test: `engine/tests/test_validate.py` (append)

**Interfaces:**
- Produces: `${memory.knowledge.<domain>}` lints clean; `${memory.<anything-else>}` raises `bad-placeholder`.

- [ ] **Step 1: Write the failing test** — append to `engine/tests/test_validate.py` (import `validate` as the file already does; use `validate.validate_doc`):

```python
class MemoryPlaceholderTest(unittest.TestCase):
    def _doc(self, ref):
        return {
            "version": 1, "name": "mem", "start": "work",
            "nodes": [{
                "id": "work", "type": "agent", "instruction": "go",
                "inputs": {"lessons": ref}, "outputs": ["note"],
                "artifact": ".maestro/x/work.md", "next": "end",
            }],
        }

    def test_memory_ref_ok(self):
        issues = validate.validate_doc(self._doc("${memory.knowledge.backend-review}"))
        self.assertFalse([i for i in issues if i.code == "bad-placeholder"], [str(i) for i in issues])

    def test_memory_ref_malformed(self):
        issues = validate.validate_doc(self._doc("${memory.oops}"))
        self.assertTrue(any(i.code == "bad-placeholder" for i in issues))
```

(If `test_validate.py` does not already `import validate`, add `import validate` after the `sys.path.insert` line, mirroring `test_resolver.py`.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 engine/tests/test_validate.py MemoryPlaceholderTest -v`
Expected: FAIL on `test_memory_ref_ok` — `${memory...}` currently hits the `else` → `bad-placeholder`.

- [ ] **Step 3: Make the edit.** In `engine/validate.py` change line 38:

```python
_PLACEHOLDER_RE = re.compile(r"\$\{([^{}]+)\}")
```

In `_validate_node`, in the placeholder loop, add a `memory` branch before the final `else` (i.e. after the `elif parts[0] == "config":` / `pass` block):

```python
            elif parts[0] == "memory":
                if not (len(parts) == 3 and parts[1] == "knowledge"):
                    issues.append(Issue("error", "bad-placeholder",
                                        f"memory ref must be ${{memory.knowledge.<domain>}}: ${{{ref}}}", w))
```

- [ ] **Step 4: Run tests**

Run: `python3 engine/tests/test_validate.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add engine/validate.py engine/tests/test_validate.py
git commit -m "$(printf 'feat(engine): validator accepts %s{memory.knowledge.*}, innermost regex\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>' '$')"
```

---

## Task 5: `skills/build-knowledge/SKILL.md`

**Files:**
- Create: `skills/build-knowledge/SKILL.md`

- [ ] **Step 1: Write the skill**

```markdown
---
name: build-knowledge
description: Bootstrap Maestro domain knowledge by scanning the codebase — writes initial knowledge files under the memory store. Front door for /build-knowledge.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, bootstrap]
---

# build-knowledge — seed domain knowledge from the codebase

Create the initial domain-knowledge files Maestro injects into future runs, by reading the
existing code. Run once per workspace; re-runnable (it MERGES, never clobbers).

## Inputs
Your instruction names the memory store paths to write and the code surface to read (the
`codebase/` repos or the single repo, their `CLAUDE.md`/`.cursor/rules`, and `docs/`).
Standalone with no paths given? Write to a sensible memory location and tell the user where.

## Method
1. **Survey the code.** Per repo: entry points, build/test/run commands, directory layout,
   house style, cross-cutting conventions, recurring gotchas. Read each repo's
   `CLAUDE.md`/rules first — they state the team's norms.
2. **Bucket by consumer.** Write one knowledge file per consuming SDLC role, plus a shared
   `codebase.md`: `plan`, `backend-design`, `frontend-design`, `backend-review`,
   `frontend-review`, `architecture-review` — each holding the standards/pitfalls a step in
   that role should know before it starts.
3. **Short and actionable** — a claim + why it matters. This text is injected into prompts;
   bloat costs tokens on every future run.
4. **Provenance.** Tag each entry `_(bootstrap)_`.
5. **Merge, don't clobber.** If a knowledge file exists, integrate new observations and keep
   human edits and accrued lessons.
6. **Index.** Write/refresh the store's `index.md` (one line per knowledge file).

## Standards
- Prefer few high-signal lessons over exhaustive dumps. Contradicting the actual code is
  worse than saying nothing.
- Do not invent conventions the code does not exhibit.

## Safety
- Read-only against the code; write only the memory store files named in your instruction.
  Never edit application code here.

## Output contract
Return `domains_written` (count of knowledge files created/updated) and `summary` (one line:
what was seeded and from where).
```

- [ ] **Step 2: Verify frontmatter parses**

Run: `python3 -c "import re,sys; t=open('skills/build-knowledge/SKILL.md').read(); assert t.startswith('---'); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add skills/build-knowledge/SKILL.md
git commit -m "$(printf 'feat(skills): build-knowledge — bootstrap domain knowledge from codebase\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 6: `skills/retrospect/SKILL.md`

**Files:**
- Create: `skills/retrospect/SKILL.md`

- [ ] **Step 1: Write the skill**

```markdown
---
name: retrospect
description: Distill a finished Maestro run into durable, provenance-tagged lessons staged for consolidation. Front door for /retrospect.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, retrospective]
---

# retrospect — turn one run's outcomes into lessons

Read a finished feature run and extract what future runs should know. You write ONLY the
per-run staging drop — never the trusted knowledge tier.

## Inputs
Your instruction names the run to read (its ledger + artifacts) and the single incoming file
to write. Standalone? Summarise to a path you choose and tell the user.

## Method
1. **Mine the ledger.** From the run's `state.yaml`: gate decisions and their
   feedback/guidance text (what a human overrode and why), per-step `visits`/`attempts`
   (loops that thrashed, steps that retried), failure reasons.
2. **Mine the artifacts.** Blocking review findings, QA failures, contract mismatches —
   especially anything that recurred.
3. **Write lessons**, bucketed by the consuming domain (which SDLC role would benefit). Each
   lesson: a short actionable claim + why. Tag provenance with this run's slug.
4. **Stage only.** Write to the incoming drop for this run. Do NOT touch the knowledge or
   candidates tiers — consolidation owns promotion.

## Standards
- A lesson is a repeatable pattern, not a one-off event narration. If it only makes sense for
  this feature, leave it out.
- Short scalars in the output; the lessons live in the file.

## Safety
- Read-only against the run; write only the single incoming file named in your instruction.

## Output contract
Return `incoming_path` (the file written), `lessons_count` (integer), and `summary` (one line).
```

- [ ] **Step 2: Verify** — `python3 -c "assert open('skills/retrospect/SKILL.md').read().startswith('---'); print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add skills/retrospect/SKILL.md
git commit -m "$(printf 'feat(skills): retrospect — distill a run into staged lessons\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 7: `skills/consolidate-memory/SKILL.md`

**Files:**
- Create: `skills/consolidate-memory/SKILL.md`

- [ ] **Step 1: Write the skill**

```markdown
---
name: consolidate-memory
description: Merge staged Maestro lessons into candidates, promote corroborated ones into trusted knowledge, and prune/cap the store. Front door for /consolidate-memory.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, consolidation]
---

# consolidate-memory — the reduce step, with corroboration before promotion

Turn per-run staging drops into trusted domain knowledge, but only promote a lesson once
MULTIPLE runs corroborate it — never on the strength of one run.

## Inputs
Your instruction names the store paths (incoming, candidates, knowledge, index) and the
promotion threshold. Standalone? Operate on the memory store and tell the user what changed.

## Method
1. **Fold incoming into candidates.** For each lesson in the incoming drops, find its
   matching candidate (same claim + domain). If found, increment its observation count and
   append the new source slug — counting DISTINCT slugs only (a lesson repeated within one
   run counts once). If new, add it as a candidate with count 1. Then clear the incoming
   drops you folded.
2. **Promote the corroborated.** Any candidate seen in **≥ threshold distinct slugs**
   (default **3**) graduates into the knowledge tier for its domain; remove it from
   candidates. Sub-threshold candidates stay and keep accruing.
3. **Prune & cap.** Dedup within knowledge; drop superseded or contradicted lessons; enforce
   a per-file size cap so injected knowledge stays small; age out candidates that have sat
   far below threshold for too long.
4. **Index.** Rewrite `index.md`.

## Standards
- Bootstrap-authored and human-authored knowledge lessons are authoritative — never demote
  or delete them for lacking a count.
- Favour a small, high-signal knowledge tier. Every promoted lesson is paid for in tokens on
  every future run that reads it.
- Never lower a lesson's count or fabricate corroboration.

## Safety
- You are the ONLY writer of the candidates and knowledge tiers. Do not edit run state or
  application code.

## Output contract
Return `promoted` (count promoted to knowledge this pass), `candidates` (count still staged),
and `summary` (one line).
```

- [ ] **Step 2: Verify** — `python3 -c "assert open('skills/consolidate-memory/SKILL.md').read().startswith('---'); print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add skills/consolidate-memory/SKILL.md
git commit -m "$(printf 'feat(skills): consolidate-memory — candidates + 3-run promotion threshold\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 8: `workflows/build-knowledge.yaml`

**Files:**
- Create: `workflows/build-knowledge.yaml`

**Interfaces:**
- Consumes: `skills/build-knowledge` (Task 5), `agents/analyst.md` (exists).

- [ ] **Step 1: Write the workflow**

```yaml
# Bootstrap domain knowledge by scanning the codebase into .maestro/memory/knowledge/.
# Run once per workspace (recommended before your first feature): /build-knowledge
# Re-runnable — it MERGES, never clobbers human edits or accrued lessons.
version: 1
name: build-knowledge
description: Seed initial domain knowledge from the existing codebase.
inputs:
  slug: {type: string, default: bootstrap, description: throwaway run id for the bootstrap}
  feature: {type: string, default: knowledge-bootstrap}
defaults:
  model: haiku
  agent: analyst
start: build
nodes:
  - id: build
    type: agent
    label: Build domain knowledge
    instruction: |
      Scan this workspace and write initial domain knowledge under .maestro/memory/knowledge/.
      Read the repos under codebase/ (or the single repo), each repo's CLAUDE.md /
      .cursor/rules, and the centralised docs/. Write knowledge/codebase.md (shared
      architecture facts, stacks, build/test commands, conventions, gotchas) and one file per
      consuming SDLC role — knowledge/plan.md, knowledge/backend-design.md,
      knowledge/frontend-design.md, knowledge/backend-review.md, knowledge/frontend-review.md,
      knowledge/architecture-review.md — each with the recurring standards/pitfalls a step in
      that role should know. Tag every entry "_(bootstrap)_". Then write/refresh
      .maestro/memory/index.md (one line per knowledge file). If knowledge files already
      exist, MERGE — do not clobber human edits or accrued lessons.
    skill: build-knowledge
    outputs: [domains_written, summary]
    artifact: ".maestro/memory/index.md"
    next: end
```

- [ ] **Step 2: Validate**

Run: `python3 engine/maestroctl.py validate workflows/build-knowledge.yaml`
Expected: JSON `{"ok": true, "errors": 0, ...}`.

- [ ] **Step 3: Commit**

```bash
git add workflows/build-knowledge.yaml
git commit -m "$(printf 'feat(workflows): build-knowledge bootstrap workflow\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 9: `workflows/retrospect.yaml`

**Files:**
- Create: `workflows/retrospect.yaml`

**Interfaces:**
- Consumes: `skills/retrospect` (Task 6), `skills/consolidate-memory` (Task 7).
- Produces: reused as a subworkflow by `archive.yaml` (Task 10). Node ids `retrospect`, `consolidate`.

- [ ] **Step 1: Write the workflow**

```yaml
# Harvest a finished run into memory: distill lessons (staged) then consolidate.
# Standalone off-cycle harvest: /maestro <slug> workflows/retrospect.yaml
# Also reused as the harvest half of workflows/archive.yaml.
version: 1
name: retrospect
description: Distill a finished run into lessons, then consolidate the memory store.
inputs:
  slug: {type: string, required: true, description: the finished feature to harvest}
  feature: {type: string, default: "${inputs.slug}"}
defaults:
  model: haiku
  agent: analyst
start: retrospect
nodes:
  - id: retrospect
    type: agent
    label: Distill lessons
    instruction: |
      Distill durable lessons from the finished run for feature "${inputs.slug}". Read its
      ledger .maestro/${inputs.slug}/state.yaml (gate decisions + their feedback/guidance
      text; per-step visits/attempts/status showing loops and retries) and the run's
      review/QA artifacts under .maestro/${inputs.slug}/. Write short, actionable,
      provenance-tagged lessons to .maestro/memory/incoming/${inputs.slug}.md, bucketed by
      the consuming domain (plan, backend-design, backend-review, ...). Do NOT write
      knowledge/ or candidates/ — only the incoming drop.
    skill: retrospect
    inputs: {slug: "${inputs.slug}"}
    outputs: [incoming_path, lessons_count, summary]
    artifact: ".maestro/memory/incoming/${inputs.slug}.md"
    next: consolidate

  - id: consolidate
    type: agent
    label: Consolidate memory
    instruction: |
      Consolidate the memory store. Fold every lesson in .maestro/memory/incoming/* into
      .maestro/memory/candidates/<domain>.md, incrementing each lesson's observation count
      and appending the DISTINCT source slug (a lesson repeated within one slug counts once).
      Promote any candidate seen in at least 3 distinct slugs into
      .maestro/memory/knowledge/<domain>.md (use config.memory.promote_threshold if the user
      set one, else 3). Dedup and prune superseded lessons, enforce a per-file size cap so
      injected knowledge stays small, age out candidates that never corroborate, rewrite
      .maestro/memory/index.md, then clear the incoming drops you folded. Bootstrap-authored
      and human-authored knowledge lessons are authoritative — keep them.
    skill: consolidate-memory
    outputs: [promoted, candidates, summary]
    artifact: ".maestro/memory/index.md"
    next: end
```

- [ ] **Step 2: Validate**

Run: `python3 engine/maestroctl.py validate workflows/retrospect.yaml`
Expected: `{"ok": true, ...}`.

- [ ] **Step 3: Commit**

```bash
git add workflows/retrospect.yaml
git commit -m "$(printf 'feat(workflows): retrospect -> consolidate harvest workflow\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 10: Archival phase — `workflows/archive.yaml` + convert `sdlc-main.yaml` `archive` node + fix e2e

**Files:**
- Create: `workflows/archive.yaml`
- Modify: `workflows/sdlc-main.yaml` (`archive` node ~lines 148-154)
- Modify: `engine/tests/test_sdlc_e2e.py` (`canned_agent_outputs` table ~lines 23-39)

**Interfaces:**
- Consumes: `workflows/retrospect.yaml` (Task 9, as a subworkflow).
- Produces: `sdlc-main`'s `archive` step now runs harvest + publish before the workflow ends. Step paths under it: `archive/harvest/retrospect`, `archive/harvest/consolidate`, `archive/publish`.

- [ ] **Step 1: Update the e2e canned table first (failing test).** In `engine/tests/test_sdlc_e2e.py`, add two entries to the `table` dict in `canned_agent_outputs` (after `"review_pack": {...},`):

```python
        "retrospect": {"incoming_path": ".maestro/memory/incoming/demo.md",
                       "lessons_count": 2, "summary": "distilled"},
        "consolidate": {"promoted": 0, "candidates": 2, "summary": "staged"},
```

- [ ] **Step 2: Run the e2e to verify it fails**

Run: `python3 engine/tests/test_sdlc_e2e.py SdlcE2E.test_happy_path -v`
Expected: FAIL — the `archive` node is still a `script` stub, so the run ends without entering `retrospect`/`consolidate`; but once we convert it (next steps) the run will drive them. (Running now documents the pre-change baseline; it will PASS again after Steps 3-4. If it already PASSES here, that only means the new table rows are unused yet.)

- [ ] **Step 3: Create `workflows/archive.yaml`**

```yaml
# Pre-merge archival phase (invoked by sdlc-main.yaml before the human merges to master):
# harvest this run's lessons into memory, then publish curated docs.
#   harvest (retrospect -> consolidate)  ->  publish (stub)
version: 1
name: archive
description: Harvest the finished feature into memory, then publish its curated docs.
inputs:
  slug: {type: string, required: true}
  feature: {type: string, default: "${inputs.slug}"}
defaults:
  model: haiku
  agent: analyst
start: harvest
nodes:
  - id: harvest
    type: subworkflow
    label: Harvest lessons into memory
    workflow: workflows/retrospect.yaml
    inputs: {slug: "${inputs.slug}", feature: "${inputs.feature}"}
    next: publish

  - id: publish
    type: script
    label: Publish curated docs (stub)
    # POC stub — wire to your doc-publishing convention: curate .maestro/<slug>/ docs into
    # the committed docs/technical|functional/ tree.
    run: [bash, -c, "echo 'publish stub: curate .maestro/${inputs.slug}/ docs into committed docs/ here'; exit 0"]
    next: end
```

- [ ] **Step 4: Convert the `sdlc-main.yaml` `archive` node.** Replace the existing `archive` node (the `type: script` stub) with:

```yaml
  - id: archive
    type: subworkflow
    label: Archival (harvest + publish)
    # Runs AFTER release approval and BEFORE the human merges the feature branch to master:
    # folds this run's lessons into domain memory, then publishes curated docs.
    workflow: workflows/archive.yaml
    inputs: {slug: "${inputs.slug}", feature: "${inputs.feature}"}
    next: end
```

- [ ] **Step 5: Validate + run the e2e**

Run: `python3 engine/maestroctl.py validate workflows/sdlc-main.yaml`
Expected: `{"ok": true, ...}` (recurses into archive.yaml → retrospect.yaml).
Run: `python3 engine/tests/test_sdlc_e2e.py -v`
Expected: PASS (all scenarios; happy_path now traverses `archive/harvest/retrospect`, `archive/harvest/consolidate`, `archive/publish`).

- [ ] **Step 6: Commit**

```bash
git add workflows/archive.yaml workflows/sdlc-main.yaml engine/tests/test_sdlc_e2e.py
git commit -m "$(printf 'feat(workflows): pre-merge archival phase (harvest + publish)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 11: Wire memory injection into the shipped steps + add "Prior lessons" sections

**Files:**
- Modify: `workflows/design.yaml` (`author_hld` ~lines 38-43; `backend_design` ~line 134; `frontend_design` ~line 147)
- Modify: `workflows/sdlc-main.yaml` (`arch_review` inputs ~line 44)
- Modify: `workflows/impl.yaml` (`review` inputs ~lines 84-86)
- Modify: `skills/{plan,backend-design,frontend-design,backend-review,frontend-review,architecture-review}/SKILL.md`

**Interfaces:**
- Consumes: the `${memory.*}` namespace (Task 3), nested resolution (Task 2).

- [ ] **Step 1: Wire `design.yaml`.** In `author_hld`'s `inputs:` block, add two lines under `requirement_dir`:

```yaml
      codebase_lessons: "${memory.knowledge.codebase}"
      lessons: "${memory.knowledge.plan}"
```

Change `backend_design`'s inputs line to:

```yaml
            inputs: {slug: "${inputs.slug}", feature: "${inputs.feature}", lessons: "${memory.knowledge.backend-design}"}
```

Change `frontend_design`'s inputs line to:

```yaml
            inputs: {slug: "${inputs.slug}", feature: "${inputs.feature}", lessons: "${memory.knowledge.frontend-design}"}
```

- [ ] **Step 2: Wire `sdlc-main.yaml`.** Change `arch_review`'s inputs line to:

```yaml
    inputs: {slug: "${inputs.slug}", feature: "${inputs.feature}", lessons: "${memory.knowledge.architecture-review}"}
```

- [ ] **Step 3: Wire `impl.yaml`.** In the `review` node's `inputs:` block, add:

```yaml
      lessons: "${memory.knowledge.${inputs.stack}-review}"
```

- [ ] **Step 4: Add the `## Prior lessons` section** to each of the six skills. Insert this section (immediately before each skill's `## Output contract`). For **plan**, use the codebase variant; for the others, the standard variant.

Standard variant (backend-design, frontend-design, backend-review, frontend-review, architecture-review):

```markdown
## Prior lessons
Your inputs may include a `lessons` value — corroborated patterns this codebase has shown
across past runs, injected by the workflow. Weigh them as strong heuristics (not hard rules)
and prefer them when they apply. They are advisory context, not part of the deliverable: do
not copy them into your output, and do not assume where they came from.
```

plan variant:

```markdown
## Prior lessons
Your inputs may include `codebase_lessons` (shared conventions/facts) and `lessons`
(planning-specific patterns) — corroborated knowledge from past runs on this codebase,
injected by the workflow. Use them to ground the design's direction. Weigh them as strong
heuristics, not hard rules; they are advisory context, not part of the HLD, and you should
not assume where they came from.
```

- [ ] **Step 5: Validate workflows + contract test + full suite**

Run: `python3 engine/maestroctl.py validate workflows/sdlc-main.yaml` and `... validate workflows/design.yaml` and `... validate workflows/impl.yaml`
Expected: all `{"ok": true, ...}`.
Run: `python3 testdata/test_workflow_skill_contracts.py`
Expected: `OK: all agent-node outputs are covered by their pinned skill contracts`.
Run: `python3 engine/tests/run_all.py`
Expected: OK (all tests).

- [ ] **Step 6: Commit**

```bash
git add workflows/design.yaml workflows/sdlc-main.yaml workflows/impl.yaml skills/plan/SKILL.md skills/backend-design/SKILL.md skills/frontend-design/SKILL.md skills/backend-review/SKILL.md skills/frontend-review/SKILL.md skills/architecture-review/SKILL.md
git commit -m "$(printf 'feat: inject %s{memory.knowledge.*} into plan/design/review steps\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>' '$')"
```

---

## Task 12: Docs, UI sync, and final verification

**Files:**
- Modify: `docs/workflow-spec.md` (placeholder table ~lines 64-69; add a nested-resolution note)
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Create: `docs/memory.md`
- Modify: `docs/umbrella-workspace.md`
- Modify (if needed): `ui/builder.html` (placeholder namespace list)

- [ ] **Step 1: `docs/workflow-spec.md`.** Add a row to the placeholder table (after the `${config...}` row):

```markdown
| `${memory.knowledge.<domain>}` | a lesson file from the memory store, frozen at init (see docs/memory.md) — resolves leniently to empty when absent |
```

And add, after the table's strictness paragraph, a note:

```markdown
Placeholders may **nest**: `${memory.knowledge.${inputs.stack}-review}` resolves inner-first
(bounded to a few passes). `${memory.*}` is read once at `init` from a per-run snapshot and
never re-read mid-run, so a run stays reproducible even as the shared store changes between
runs.
```

- [ ] **Step 2: `CLAUDE.md`.** Add a subsection under the repo overview (near the `.maestro/<slug>/` description) documenting the store:

```markdown
## The memory store — `.maestro/memory/`

Repo/umbrella-level, git-tracked, shared across slugs. Three tiers: `incoming/<slug>.md`
(per-run retrospective drops, race-free), `candidates/<domain>.md` (accruing, counted, NOT
injected), `knowledge/<domain>.md` (promoted + injected via `${memory.knowledge.<domain>}`).
Lessons promote from candidates to knowledge only after **≥3 distinct runs** corroborate them
(consolidate skill; bootstrap and humans write knowledge directly). The engine only READS the
knowledge tier, once, at `init`, freezing a per-run `memory-snapshot.json` — writes are done
by the `build-knowledge` / `retrospect` / `consolidate-memory` skills. Full conventions:
`docs/memory.md`.
```

- [ ] **Step 3: `README.md`.** Under the customizing/"improves over time" area, add:

```markdown
- **Memory (improves over time).** Run `/build-knowledge` once per workspace to seed
  `.maestro/memory/knowledge/` from your codebase; the design/review steps read it. After a
  feature, the pre-merge archival phase distills lessons and consolidates them — a lesson
  becomes trusted only once ≥3 runs corroborate it. See [docs/memory.md](docs/memory.md).
```

- [ ] **Step 4: Create `docs/memory.md`** with the full conventions (store layout + three tiers, lesson shape with provenance and `_(seen: N — slugs)_`, the corroboration threshold and its default of 3 + `config.memory.promote_threshold` override + bootstrap/human bypasses, the freeze-at-init rule, and the `bootstrap → run → release → archival (harvest+publish) → merge to master` lifecycle). Base the content on the approved spec `docs/superpowers/specs/2026-07-13-maestro-memory-design.md` (sections "The store", "Bootstrap", "Read path", "Consolidation", "Archival phase", "Data flow").

- [ ] **Step 5: `docs/umbrella-workspace.md`.** In "The setup, in order", add a bullet:

```markdown
- **Seed domain knowledge.** After installing, run `/build-knowledge` once from the umbrella
  root to populate `.maestro/memory/knowledge/` from the cloned repos + their `CLAUDE.md` and
  `docs/`. Feature runs read this to ground their designs and reviews.
```

And under "Running a feature", add the ordering contract:

```markdown
> Release ordering: **approve release → archival (harvest lessons into memory + publish
> curated docs) → merge the feature branch to master.** Archival is the last automated phase;
> Maestro does not perform the merge itself.
```

- [ ] **Step 6: UI namespace (only if the builder flags it).** Check whether the builder enumerates placeholder namespaces for client-side validation:

Run: `grep -n "config" ui/builder.html | grep -i "placeholder\|namespace\|inputs\.\|steps\." | head`
If a namespace allow-list exists (e.g. an array containing `"inputs"`, `"steps"`, `"config"`), add `"memory"` to it. If no such list exists, skip.

- [ ] **Step 7: Re-embed UI schema/lint + run the sync test**

Run: `python3 ui/embed.py`
Run: `python3 testdata/test_ui_schema_sync.py`
Expected: PASS.

- [ ] **Step 8: Full green sweep**

Run: `python3 engine/tests/run_all.py`
Run: `python3 testdata/test_workflow_skill_contracts.py`
Run: `python3 engine/maestroctl.py validate workflows/sdlc-main.yaml`
Run: `python3 engine/maestroctl.py validate workflows/build-knowledge.yaml`
Run: `python3 engine/maestroctl.py validate workflows/retrospect.yaml`
Expected: all green / `{"ok": true}`.

- [ ] **Step 9: Commit**

```bash
git add docs/workflow-spec.md CLAUDE.md README.md docs/memory.md docs/umbrella-workspace.md ui/builder.html
git commit -m "$(printf 'docs: memory store conventions, spec/README/umbrella + UI namespace\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Self-Review (run after drafting; fix inline)

**Spec coverage** — every spec section maps to a task: store layout → T8-T11 paths + docs T12; bootstrap → T5,T8; read path/freeze → T3; nested placeholders → T2; consolidation/threshold(3) → T7,T9; candidates tier → T7,T9 (skill/instruction-driven, no engine code — the tiers are directories the skills manage); archival before merge → T10; wiring/idea-building → T11; validator → T4; token posture → T7 (cap) + T11 (per-domain); tests → T1-T4,T10,T11; docs → T12.

**Placeholder scan** — no TBD/TODO; every code step shows complete code; doc-heavy `docs/memory.md` (T12 S4) references exact spec sections to transcribe rather than inventing content.

**Type/name consistency** — node output fields match skill contracts exactly: build-knowledge `[domains_written, summary]`; retrospect `[incoming_path, lessons_count, summary]`; consolidate `[promoted, candidates, summary]`. Memory namespace `${memory.knowledge.<domain>}` identical in engine (T3), validator (T4), workflows (T11), docs (T12). e2e canned keys `retrospect`/`consolidate` match archive.yaml→retrospect.yaml node ids.

**Note on the candidates/promotion logic:** it lives in the `consolidate-memory` SKILL (LLM-driven file manipulation), not in engine Python — by design (Global Constraint "engine never writes memory content"). There is therefore no engine unit test for the count/threshold arithmetic; the corroboration behavior is specified in the skill and exercised by real runs. If you later want a deterministic guard, add a small stdlib `validate_memory.py` + tests in a follow-up (out of scope here).
