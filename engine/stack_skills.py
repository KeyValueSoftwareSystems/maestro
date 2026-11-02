#!/usr/bin/env python3
"""Which installed stack skills apply to a repository.

A repository's stack comes from maestro.config.yaml (`repos.<repo>.stack`, one name or a
comma-separated list such as `go, db`). The skills that apply are the installed ones whose
frontmatter `tags:` carry `stack:<name>` — in any host skills directory (.claude/skills,
.agents/skills, .cursor/skills). The implementation pool hands them to the implement, review and
fix steps, so each stack's conventions are applied instead of left to chance.

  stack_skills.py [--root .] --repo R      prints {stacks_csv, skills_csv}
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_config  # noqa: E402

HOST_DIRS = (".claude/skills", ".agents/skills", ".cursor/skills")
_TAG_RE = re.compile(r"stack:([A-Za-z0-9_+-]+)")


def repo_stacks(root, repo):
    try:
        config = project_config.load(root) or {}
    except project_config.ConfigError:
        return []
    entry = (config.get("repos") or {}).get(repo)
    value = entry.get("stack") if isinstance(entry, dict) else None
    if isinstance(value, list):
        names = value
    else:
        names = str(value or "").split(",")
    return [n.strip().lower() for n in names if str(n).strip()]


def _frontmatter_tags(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read(4096)
    except OSError:
        return set()
    if not text.startswith("---"):
        return set()
    end = text.find("\n---", 3)
    block = text[3:end if end > 0 else len(text)]
    tags = next((line for line in block.splitlines() if line.strip().startswith("tags:")), "")
    return {m.lower() for m in _TAG_RE.findall(tags)}


def installed_for(root, stacks):
    wanted = set(stacks)
    found = []
    for host in HOST_DIRS:
        base = os.path.join(root, host)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if name in found:
                continue
            if _frontmatter_tags(os.path.join(base, name, "SKILL.md")) & wanted:
                found.append(name)
    return found


def for_repo(root, repo):
    stacks = repo_stacks(root, repo)
    return stacks, installed_for(root, stacks) if stacks else []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", required=True)
    args = parser.parse_args(argv)
    stacks, skills = for_repo(args.root, args.repo)
    print(json.dumps({"stacks_csv": ",".join(stacks), "skills_csv": ",".join(skills)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
