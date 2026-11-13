"""The run brief: what every agent step should know about the run before it starts.

Without it, "what happened before" reaches an agent only where a workflow author wired it in by
hand. The engine builds the brief from the ledger, so every step starts from the same facts:

  none     nothing (a narrowly scoped repair step)
  minimal  the feature, the run mode, where the run is, and the documents earlier steps produced
           (the default)
  full     minimal plus the stage checklist, the person's and autopilot's gate decisions with
           their feedback, and the notes recorded mid-run

An agent node picks its level with `brief:` (workflow `defaults.brief`, else minimal).
render_agent_prompt inlines it; `maestroctl brief` prints it, and every serving call keeps
`.maestro/runs/<slug>/.engine/run-brief.md` current with the full brief.
"""
import os

try:
    import state as statemod
    import todo as todomod
except ImportError:
    from . import state as statemod, todo as todomod

BRIEF_FILE = f"{statemod.ENGINE_DIR}/run-brief.md"  # relative to the run folder

LEVELS = ("none", "minimal", "full")
DEFAULT_LEVEL = "minimal"
MAX_GATES = 8
MAX_NOTES = 5
MAX_DOCUMENTS = 25


def level_for(run, frame, node):
    level = node.get("brief") or run.defaults(frame, "brief") or DEFAULT_LEVEL
    return level if level in LEVELS else DEFAULT_LEVEL


def _documents(run, current):
    """Artifacts recorded by finished steps, newest last, without the current step's own."""
    seen, docs = set(), []
    steps = run.state.get("steps") or {}
    for path, entry in sorted(steps.items(), key=lambda kv: kv[1].get("finished_at") or ""):
        if path == current or entry.get("status") != "done":
            continue
        for rel in entry.get("artifact") or []:
            # a step's working file under .engine/ (a question queue) is not a document to read
            if isinstance(rel, str) and f"/{statemod.ENGINE_DIR}/" in "/" + rel.replace(os.sep, "/"):
                continue
            if isinstance(rel, str) and rel not in seen and os.path.exists(
                    rel if os.path.isabs(rel) else os.path.join(run.root, rel)):
                seen.add(rel)
                docs.append((rel, path))
    return docs[-MAX_DOCUMENTS:]


def build(run, path, level=DEFAULT_LEVEL):
    if level == "none":
        return ""
    state = run.state
    inputs = state.get("inputs") or {}
    feature = inputs.get("feature") or inputs.get("slug") or run.slug
    mode = (state.get("run") or {}).get("mode") or "human"
    lines = [f"- Feature: {feature} (`{run.slug}`)", f"- Run mode: {mode}",
             f"- This step: `{path}`"]
    docs = _documents(run, path)
    if docs:
        lines.append("- Documents so far (read only what your task needs):")
        lines.extend(f"  - {rel} (from `{step}`)" for rel, step in docs)
    if level == "full":
        todo = todomod.build(run)
        tasks = todomod.flat(todo)
        if tasks:
            lines.append("- Stages:")
            lines.extend(f"  - [{t['status']}] {t['content']}" for t in tasks)
        gates = (state.get("gates") or [])[-MAX_GATES:]
        if gates:
            lines.append("- Decisions at gates (latest last):")
            for gate in gates:
                who = "autopilot" if gate.get("auto") else (
                    "engine recovery" if gate.get("synthesized") else "person")
                said = f" — \"{gate['input']}\"" if gate.get("input") else ""
                lines.append(f"  - `{gate['step']}` → {gate['option']} ({who}){said}")
        notes = (state.get("notes") or [])[-MAX_NOTES:]
        if notes:
            lines.append("- Notes recorded mid-run:")
            lines.extend(f"  - {note.get('text', '')}" for note in notes)
    return "\n".join(lines)


def prompt_section(run, frame, node, path):
    text = build(run, path, level_for(run, frame, node))
    if not text:
        return []
    return ["Run brief (context only — your instruction above decides the task):", text, ""]


def write_file(run):
    """Keep `<feature dir>/.engine/run-brief.md` current with the full brief."""
    folder = statemod.feature_dir(run.slug, run.root)
    if not os.path.isdir(folder):
        return None
    cursors = (run.state.get("run") or {}).get("cursors") or []
    body = build(run, ", ".join(cursors) or "-", "full")
    path = os.path.join(folder, *BRIEF_FILE.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# Run brief — {run.slug}\n\n{body}\n")
    return path
