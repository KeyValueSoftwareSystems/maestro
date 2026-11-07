#!/usr/bin/env python3
"""
Import per-stack skills from ECC (github.com/affaan-m/ECC, MIT) into this pack, adapted to
our frontmatter contract:
  - skills gain  tags: [stack:<x>, <kind>]  and  allowed-tools
  - ECC's per-stack reviewer agents become `<stack>-review` checklist skills tagged
    [stack:<x>, review] — no per-stack agents: roles are agents, stacks are skills
  - MIT attribution recorded in frontmatter metadata + ATTRIBUTIONS.md

Curation lives in the STACKS manifest below: language / framework stacks only.
Domain packs (healthcare, homelab, finance, DeFi, marketing, scientific, crypto) and
harness-internal skills (autonomous-loops, hooks, gan-*, agentic-os, ...) are deliberately
excluded. Re-runnable: overwrites the imported files, never touches hand-written ones.
"""
import json
import os
import re
import sys
import urllib.request

RAW = "https://raw.githubusercontent.com/affaan-m/ECC/HEAD"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__)))  # overridden by argv[1]

ORIGIN = "ECC (github.com/affaan-m/ECC), MIT — Copyright (c) 2026 Affaan Mustafa"

# stack -> {"skills": [...], "reviews": [...]}
# "reviews" are ECC reviewer agents, imported as `<stack>-review` checklist SKILLS: a stack is
# knowledge, not a role, so it reaches the one `reviewer` role (and the implementer and fixer)
# through stack_skills.py like every other stack skill. Frameworks carry their own stack tag
# (django, fastapi, pytorch), so a plain-Python repository is not handed Django's conventions.
STACKS = {
    "go": {
        "skills": ["golang-patterns", "golang-testing"],
        "reviews": ["go-reviewer"],
    },
    "java": {
        "skills": ["java-coding-standards", "jpa-patterns",
                   "springboot-patterns", "springboot-security", "springboot-tdd",
                   "springboot-verification", "quarkus-patterns", "quarkus-security",
                   "quarkus-tdd", "quarkus-verification"],
        "reviews": ["java-reviewer"],
    },
    "kotlin": {
        "skills": ["kotlin-patterns", "kotlin-coroutines-flows",
                   "kotlin-exposed-patterns", "kotlin-ktor-patterns", "kotlin-testing"],
        "reviews": ["kotlin-reviewer"],
    },
    "python": {
        "skills": ["python-patterns", "python-testing"],
        "reviews": ["python-reviewer"],
    },
    "django": {
        "skills": ["django-patterns", "django-security", "django-tdd",
                   "django-verification", "django-celery"],
        "reviews": ["django-reviewer"],
    },
    "fastapi": {
        "skills": ["fastapi-patterns"],
        "reviews": ["fastapi-reviewer"],
    },
    "pytorch": {
        "skills": ["pytorch-patterns"],
        "reviews": [],
    },
    "react": {
        "skills": ["react-patterns", "react-testing", "react-performance",
                   "react-native-patterns", "nextjs-turbopack"],
        "reviews": ["react-reviewer"],
    },
    "vue": {
        "skills": ["vue-patterns", "nuxt4-patterns"],
        "reviews": ["vue-reviewer"],
    },
    "angular": {
        "skills": ["angular-developer"],
        "reviews": [],
    },
    "node": {
        "skills": ["nestjs-patterns", "vite-patterns"],
        "reviews": ["typescript-reviewer", "type-design-analyzer"],
    },
    "rust": {
        "skills": ["rust-patterns", "rust-testing"],
        "reviews": ["rust-reviewer"],
    },
    "flutter": {
        "skills": ["dart-flutter-patterns", "flutter-dart-code-review"],
        "reviews": ["flutter-reviewer"],
    },
    "android": {
        "skills": ["android-clean-architecture", "compose-multiplatform-patterns"],
        "reviews": [],
    },
    "db": {
        "skills": ["postgres-patterns", "mysql-patterns", "redis-patterns",
                   "prisma-patterns", "clickhouse-io", "database-migrations"],
        "reviews": ["database-reviewer"],
    },
}

# What each review checklist covers, for its skill's name line.
REVIEW_SUBJECTS = {
    "go-reviewer": "Go", "java-reviewer": "Java (Spring Boot, Quarkus)",
    "kotlin-reviewer": "Kotlin", "python-reviewer": "Python", "django-reviewer": "Django",
    "fastapi-reviewer": "FastAPI", "react-reviewer": "React", "vue-reviewer": "Vue",
    "typescript-reviewer": "TypeScript and JavaScript",
    "type-design-analyzer": "TypeScript type design", "rust-reviewer": "Rust",
    "flutter-reviewer": "Flutter and Dart", "database-reviewer": "database (PostgreSQL)",
}
# Agent framing a checklist drops: the persona and its procedure, its own verdict and report
# format (in a Maestro run the review skill owns the report and the engine decides blocking),
# and cross-references to sibling agents that are not shipped.
REVIEW_DROP = ("prompt defense baseline", "approval criteria", "output format",
               "review output format", "summary format", "review summary", "your role",
               "workflow", "review workflow", "when invoked", "scope vs", "related")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "maestro-import"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def strip_dropped_refs(body):
    """Remove mentions of per-stack agents we deliberately DON'T ship (build-resolvers).
    ECC bodies sometimes list them in a trailing 'Agents:' line; strip that clause so an
    imported skill never points at a non-existent agent. Idempotent."""
    # a clause introduced by a separator:  ", `x-build-resolver` <phrase>"  /  "; ... "
    body = re.sub(r"[,;]\s*`?[\w-]*build-resolver`?[^,;\n]*", "", body)
    # a leading clause before a separator:  "`x-build-resolver` <phrase>, "
    body = re.sub(r"`?[\w-]*build-resolver`?[^,;\n]*[,;]\s*", "", body)
    return body


def split_frontmatter(text):
    """Return (fm_lines, body) where fm is the text between the first two --- fences."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:]).lstrip("\n")
    return [], text


def fm_get(fm_lines, key):
    for ln in fm_lines:
        if ln.startswith(key + ":"):
            return ln[len(key) + 1:].strip()
    return None


def skill_kind(name):
    n = name.lower()
    if any(k in n for k in ("testing", "-tdd", "-test", "verification")):
        return "testing"
    if "security" in n:
        return "security"
    return "patterns"


def import_skill(name, stack, report):
    try:
        text = fetch(f"{RAW}/skills/{name}/SKILL.md")
    except Exception as e:  # noqa: BLE001
        report["missing_skills"].append((name, str(e)))
        return
    fm, body = split_frontmatter(text)
    body = strip_dropped_refs(body)
    desc = fm_get(fm, "description") or f"{name} — imported reference skill."
    # de-quote a quoted description
    if desc[:1] in "'\"" and desc[-1:] == desc[:1]:
        desc = desc[1:-1]
    kind = skill_kind(name)
    tags = f"[stack:{stack}, {kind}]"
    new = (
        "---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        "allowed-tools: Read, Grep, Glob, Bash\n"
        f"tags: {tags}\n"
        "---\n\n"
        f"{body}\n"
    )
    # per-stack reference skills live under skills/stacks/<stack>/ in the organized tree
    dst = os.path.join(ROOT, "skills", "stacks", stack, name)
    os.makedirs(dst, exist_ok=True)
    with open(os.path.join(dst, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(new)
    report["skills"].append((name, stack, kind))


def review_skill_name(agent):
    return "type-design-review" if agent == "type-design-analyzer" else \
        agent.replace("-reviewer", "-review")


def review_skill(agent, stack, text):
    """An ECC reviewer agent's checklist as a `<stack>-review` skill: the frontmatter is
    rewritten, every section whose heading is agent framing (REVIEW_DROP, or the H1 persona
    title) is dropped, and the rest is kept verbatim. Headings inside code fences are text."""
    _fm, body = split_frontmatter(text)
    body = strip_dropped_refs(body)
    shipped = {review_skill_name(a) for spec in STACKS.values() for a in spec["reviews"]}

    def sibling(match):  # `go-reviewer` -> `go-review` when that checklist ships
        name = f"{match.group(1)}-review"
        return f"`{name}`" if name in shipped else match.group(0)

    kept, keep, fenced, dropped_level, procedure = [], False, False, None, False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        heading = None if fenced else re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip().lower()
            if dropped_level is not None and level > dropped_level:
                continue  # a subsection of dropped framing (e.g. a workflow's steps)
            dropped_level = None
            keep = level > 1 and not title.startswith(REVIEW_DROP)
            if not keep:
                dropped_level = level
        if not keep or dropped_level is not None and not heading:
            continue
        # the agent's own procedure ("Then proceed: 1. Run git diff …") and persona lines
        if not fenced and line.strip() == "Then proceed:":
            procedure = True
        if procedure:
            procedure = bool(line.strip())
            continue
        if not fenced and re.match(r"^You (are|DO NOT|do not|must)\b", line):
            continue
        # hand-offs to agents that do not ship, and paths to agent files, are dropped
        if "security-reviewer" in line or "agents/" in line:
            continue
        kept.append(re.sub(r"`([\w-]+)-reviewer`", sibling, line))
    subject = REVIEW_SUBJECTS.get(agent, stack)
    name = review_skill_name(agent)
    return name, (
        "---\n"
        f"name: {name}\n"
        f"description: {subject} review checklist — what to check in {subject} code, by "
        "severity. A reference for writing and reviewing it; in a workflow run the review step "
        "records each problem as a finding and the engine decides what blocks.\n"
        "allowed-tools: Read, Grep, Glob, Bash\n"
        f"tags: [stack:{stack}, review]\n"
        "---\n\n"
        f"# {subject} review checklist\n\n"
        f"Use this when writing or reviewing {subject} code. The severities say how serious a "
        "problem is; they are guidance for a finding's severity, not a verdict.\n\n"
        + "\n".join(kept).strip() + "\n"
    )


def write_review(agent, stack, text, report):
    name, content = review_skill(agent, stack, text)
    dst = os.path.join(ROOT, "skills", "stacks", stack, name)
    os.makedirs(dst, exist_ok=True)
    with open(os.path.join(dst, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(content)
    report["reviews"].append((name, stack, agent))


def import_review(agent, stack, report):
    try:
        text = fetch(f"{RAW}/agents/{agent}.md")
    except Exception as e:  # noqa: BLE001
        report["missing_reviews"].append((agent, str(e)))
        return
    write_review(agent, stack, text, report)


def main():
    global ROOT
    if len(sys.argv) > 1:
        ROOT = os.path.abspath(sys.argv[1])
    report = {"skills": [], "reviews": [], "missing_skills": [], "missing_reviews": []}
    for stack, spec in STACKS.items():
        for s in spec["skills"]:
            import_skill(s, stack, report)
        for a in spec["reviews"]:
            import_review(a, stack, report)
    print(json.dumps({
        "imported_skills": len(report["skills"]),
        "imported_reviews": len(report["reviews"]),
        "missing_skills": report["missing_skills"],
        "missing_reviews": report["missing_reviews"],
        "stacks": sorted(STACKS.keys()),
    }, indent=2))
    # write a machine list for the attribution file
    with open(os.path.join(ROOT, ".ecc-import-manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)


if __name__ == "__main__":
    main()
