#!/usr/bin/env python3
"""
Import per-stack skills + agents from ECC (github.com/affaan-m/ECC, MIT) into this
pack, adapted to our frontmatter contract:
  - skills gain  tags: [stack:<x>, <kind>]  and  allowed-tools
  - agents gain  tags: [stack:<x>, <role>]
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

# stack -> {"skills": [...], "agents": [...]}
STACKS = {
    "go": {
        "skills": ["golang-patterns", "golang-testing"],
        "agents": ["go-reviewer"],
    },
    "java": {
        "skills": ["java-coding-standards", "jpa-patterns",
                   "springboot-patterns", "springboot-security", "springboot-tdd",
                   "springboot-verification", "quarkus-patterns", "quarkus-security",
                   "quarkus-tdd", "quarkus-verification"],
        "agents": ["java-reviewer"],
    },
    "kotlin": {
        "skills": ["kotlin-patterns", "kotlin-coroutines-flows",
                   "kotlin-exposed-patterns", "kotlin-ktor-patterns", "kotlin-testing"],
        "agents": ["kotlin-reviewer"],
    },
    "python": {
        "skills": ["python-patterns", "python-testing", "fastapi-patterns",
                   "django-patterns", "django-security", "django-tdd",
                   "django-verification", "django-celery", "pytorch-patterns"],
        "agents": ["python-reviewer", "fastapi-reviewer", "django-reviewer"],
    },
    "react": {
        "skills": ["react-patterns", "react-testing", "react-performance",
                   "react-native-patterns", "nextjs-turbopack"],
        "agents": ["react-reviewer"],
    },
    "vue": {
        "skills": ["vue-patterns", "nuxt4-patterns"],
        "agents": ["vue-reviewer"],
    },
    "angular": {
        "skills": ["angular-developer"],
        "agents": [],
    },
    "node": {
        "skills": ["nestjs-patterns", "vite-patterns"],
        "agents": ["typescript-reviewer", "type-design-analyzer"],
    },
    "rust": {
        "skills": ["rust-patterns", "rust-testing"],
        "agents": ["rust-reviewer"],
    },
    "flutter": {
        "skills": ["dart-flutter-patterns", "flutter-dart-code-review"],
        "agents": ["flutter-reviewer"],
    },
    "android": {
        "skills": ["android-clean-architecture", "compose-multiplatform-patterns"],
        "agents": [],
    },
    "db": {
        "skills": ["postgres-patterns", "mysql-patterns", "redis-patterns",
                   "prisma-patterns", "clickhouse-io", "database-migrations"],
        "agents": ["database-reviewer"],
    },
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "kv-skills-import"})
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
    dst = os.path.join(ROOT, "skills", name)
    os.makedirs(dst, exist_ok=True)
    with open(os.path.join(dst, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(new)
    report["skills"].append((name, stack, kind))


def agent_role(name):
    n = name.lower()
    if "build-resolver" in n or "resolver" in n:
        return "build-resolver"
    if "reviewer" in n:
        return "reviewer"
    return "analyst"


def import_agent(name, stack, report):
    try:
        text = fetch(f"{RAW}/agents/{name}.md")
    except Exception as e:  # noqa: BLE001
        report["missing_agents"].append((name, str(e)))
        return
    fm, body = split_frontmatter(text)
    body = strip_dropped_refs(body)
    keep = [ln for ln in fm if not ln.startswith("tags:")]
    role = agent_role(name)
    new_fm = keep + [f"tags: [stack:{stack}, {role}]"]
    new = (
        "---\n" + "\n".join(new_fm) + "\n---\n\n"
        f"{body}\n"
    )
    with open(os.path.join(ROOT, "agents", f"{name}.md"), "w", encoding="utf-8") as fh:
        fh.write(new)
    report["agents"].append((name, stack, role))


def main():
    global ROOT
    if len(sys.argv) > 1:
        ROOT = os.path.abspath(sys.argv[1])
    report = {"skills": [], "agents": [], "missing_skills": [], "missing_agents": []}
    for stack, spec in STACKS.items():
        for s in spec["skills"]:
            import_skill(s, stack, report)
        for a in spec["agents"]:
            import_agent(a, stack, report)
    print(json.dumps({
        "imported_skills": len(report["skills"]),
        "imported_agents": len(report["agents"]),
        "missing_skills": report["missing_skills"],
        "missing_agents": report["missing_agents"],
        "stacks": sorted(STACKS.keys()),
    }, indent=2))
    # write a machine list for the attribution file
    with open(os.path.join(ROOT, ".ecc-import-manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)


if __name__ == "__main__":
    main()
