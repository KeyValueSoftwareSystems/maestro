#!/usr/bin/env bash
# Repo checks: size limits, Maestro-free agent skills, and workflow wiring.
# Run before every commit: bash scripts/check.sh
set -u
cd "$(dirname "$0")/.."
fail=0
err() { echo "FAIL: $*"; fail=1; }

n=$(wc -l < AGENTS.md)
if [ "$n" -gt 150 ]; then err "AGENTS.md has $n lines (max 150)"
elif [ "$n" -gt 100 ]; then echo "WARN: AGENTS.md has $n lines (target 100)"; fi

# Every skill, reference and template stays within 200 lines.
while read -r f; do
  n=$(wc -l < "$f")
  [ "$n" -le 200 ] || err "$f has $n lines (max 200)"
done < <(find skills stacks -name '*.md')

# Only the lead skill may know about Maestro.
while read -r f; do
  grep -qi 'maestro' "$f" && err "$f mentions Maestro (only skills/maestro may)"
done < <(find skills stacks -name '*.md' ! -path 'skills/maestro/*')

# Every skill has a name in its frontmatter that matches its folder.
for d in skills/*/ skills/agents/*/ stacks/*/; do
  [ "$d" = skills/agents/ ] && continue
  name="$(basename "$d")"
  head -5 "$d/SKILL.md" 2>/dev/null | grep -qx "name: $name" || err "$d/SKILL.md: missing or wrong 'name: $name'"
done
# Agents install next to the other skills, so their names must not clash.
for d in skills/agents/*/; do [ ! -d "skills/$(basename "$d")" ] || err "$d: also in skills/"; done
# init names the stack skills it can choose, so that list must match stacks/.
for d in stacks/*/; do grep "stack skills from:" workflows/init.yaml | grep -qw "$(basename "$d")" || err "workflows/init.yaml doesn't list stack $d"; done

# Every agent and workflow file that a workflow names exists, and every workflow has a command.
agents=" worker $(ls skills/agents | tr '\n' ' ') "
while read -r wf; do
  for a in $(sed -n 's/^[ -]*agent: *\([a-z-]*\).*/\1/p' "$wf"); do
    case "$agents" in *" $a "*) ;; *) err "$wf: unknown agent '$a'" ;; esac
  done
  for w in $(sed -n 's/^[ -]*workflow: *\([^ ]*\).*/\1/p' "$wf"); do
    [ -f "workflows/$w" ] || err "$wf: workflow file '$w' not found"
  done
done < <(find workflows -name '*.yaml')
for wf in workflows/*.yaml; do
  grep -q "workflows/$(basename "$wf")" commands/*.md || err "$wf: no command in commands/ runs it"
done

# YAML parses, when PyYAML is available.
if python3 -c 'import yaml' 2>/dev/null; then
  for wf in $(find workflows -name '*.yaml'); do
    python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1]))' "$wf" 2>/dev/null || err "$wf: invalid YAML"
  done
else
  echo "SKIP: YAML parse (PyYAML not installed)"
fi

[ "$fail" = 0 ] && echo "All checks passed."
exit "$fail"
