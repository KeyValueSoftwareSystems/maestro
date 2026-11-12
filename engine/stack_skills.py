#!/usr/bin/env python3
"""Which installed stack skills apply to a repository.

A repository's stack comes from maestro.config.yaml (`repos.<repo>.stack`, one name or a
comma-separated list such as `go, db`). The skills that apply are the installed ones whose
frontmatter `tags:` carry `stack:<name>` — in any host skills directory (.claude/skills,
.agents/skills, .cursor/skills). The implementation pool hands them to the implement, review and
fix steps, so each stack's conventions are applied instead of left to chance.

Each step is handed only what its job reads, by the skill's kind tag (`tags: [stack:go, review]`):
the steps that write code (`write`: implement, fix) get everything except the `review`
checklists; the reviewer (`review`) gets the `review` checklists and the `security` skills. A
stack that ships no review checklist gives the reviewer its other skills instead, and a skill
with no kind tag goes to both.

  stack_skills.py [--root .] --repo R [--role write|review]
                                           prints {stacks_csv, skills_csv}
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
ROLES = ("write", "review")
KINDS = ("patterns", "testing", "security", "review")
REVIEW_KINDS = {"review", "security"}


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
    stacks = {m.lower() for m in _TAG_RE.findall(tags)}
    words = {w.lower() for w in re.findall(r"[A-Za-z0-9_+:-]+", tags.partition(":")[2])}
    return stacks, words & set(KINDS)


def _installed(root, stacks):
    """[(name, its matching stacks, its kinds)] for the installed skills of `stacks`."""
    wanted = set(stacks)
    found, names = [], set()
    for host in HOST_DIRS:
        base = os.path.join(root, host)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if name in names:
                continue
            tagged, kinds = _frontmatter_tags(os.path.join(base, name, "SKILL.md"))
            if tagged & wanted:
                names.add(name)
                found.append((name, tagged & wanted, kinds))
    return found


def _for_role(skills, role):
    if role == "write":
        return [name for name, _stacks, kinds in skills if kinds != {"review"}]
    # stacks that ship a review checklist: the reviewer reads that, not the pattern guides
    with_checklist = {s for _name, stacks, kinds in skills if "review" in kinds for s in stacks}
    return [name for name, stacks, kinds in skills
            if not kinds or kinds & REVIEW_KINDS or not stacks & with_checklist]


def installed_for(root, stacks, role=None):
    skills = _installed(root, stacks)
    return _for_role(skills, role) if role else [name for name, _s, _k in skills]


def for_repo(root, repo, role=None):
    stacks = repo_stacks(root, repo)
    return stacks, installed_for(root, stacks, role) if stacks else []


def csv_fields(root, repo):
    """The claim outputs: every stack skill, and the lists for the writing and review steps."""
    stacks = repo_stacks(root, repo)
    skills = _installed(root, stacks) if stacks else []
    return {"stacks_csv": ",".join(stacks),
            "stack_skills_csv": ",".join(name for name, _s, _k in skills),
            "write_skills_csv": ",".join(_for_role(skills, "write")),
            "review_skills_csv": ",".join(_for_role(skills, "review"))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--role", choices=ROLES, help="only the skills this kind of step reads")
    args = parser.parse_args(argv)
    stacks, skills = for_repo(args.root, args.repo, args.role)
    print(json.dumps({"stacks_csv": ",".join(stacks), "skills_csv": ",".join(skills)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
