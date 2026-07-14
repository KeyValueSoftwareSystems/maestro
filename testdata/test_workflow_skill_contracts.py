#!/usr/bin/env python3
"""Anti-drift check: every agent node's declared `outputs:` must be covered by the
pinned skill's `## Output contract` section, and every pinned skill must exist.

This is the guard for the class of bug where a workflow node declares
`outputs: [passed, summary]` but the skill's contract returns different field names —
the engine's `complete` then rejects the step at runtime (exit 4). Runs without an LLM.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))
import wf  # noqa: E402

SKILLS_DIR = os.path.join(ROOT, "skills")
WORKFLOWS_DIR = os.path.join(ROOT, "workflows")

# Field names a skill legitimately never echoes verbatim in prose (routing-only booleans
# whose meaning the contract states differently) — kept empty on purpose; add with a reason.
ALLOW_MISSING = {}


def expand_skill(name):
    """Resolve a skill pin to the concrete skill file names it can dispatch to."""
    if name is None:
        return []
    if "${inputs.stack}" in name:
        return [name.replace("${inputs.stack}", s) for s in ("backend", "frontend")]
    if "${" in name:
        return []  # other placeholders — can't resolve statically, skip
    return [name]


def _index_skills():
    """Map skill name -> SKILL.md path. The source tree groups skills into category
    folders (core/, stacks/<x>/, maestro), so locate each by walking, not a fixed depth.
    The skill's identity is its directory name (== frontmatter name), unique across the tree."""
    index = {}
    for dirpath, _dirs, files in os.walk(SKILLS_DIR):
        if "SKILL.md" in files:
            index[os.path.basename(dirpath)] = os.path.join(dirpath, "SKILL.md")
    return index


_SKILL_INDEX = _index_skills()


def output_contract_text(skill_name):
    path = _SKILL_INDEX.get(skill_name)
    if path is None or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    out, capturing = [], False
    for line in lines:
        if line.startswith("## Output contract"):
            capturing = True
            continue
        if capturing and line.startswith("## "):
            break
        if capturing:
            out.append(line)
    return "\n".join(out)


def iter_agent_nodes(nodes):
    for node in nodes or []:
        ntype = node.get("type", "agent")
        if ntype == "agent":
            yield node
        elif ntype == "parallel":
            for branch in node.get("branches") or []:
                yield from iter_agent_nodes(branch.get("steps"))


def main():
    problems = []
    for fname in sorted(os.listdir(WORKFLOWS_DIR)):
        if not fname.endswith(".yaml"):
            continue
        doc = wf.load_file(os.path.join(WORKFLOWS_DIR, fname))
        for node in iter_agent_nodes(doc.get("nodes")):
            skill = node.get("skill")
            outputs = node.get("outputs") or []
            for skill_name in expand_skill(skill):
                text = output_contract_text(skill_name)
                if text is None:
                    problems.append(f"{fname}:{node['id']} pins skill '{skill_name}' "
                                    f"but no skills/**/{skill_name}/SKILL.md exists")
                    continue
                for field in outputs:
                    if field in ALLOW_MISSING:
                        continue
                    if field not in text:
                        problems.append(
                            f"{fname}:{node['id']} declares output '{field}' but "
                            f"skill '{skill_name}' Output contract never mentions it")
    if problems:
        print("FAIL: workflow/skill contract drift")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("OK: all agent-node outputs are covered by their pinned skill contracts")


if __name__ == "__main__":
    main()
