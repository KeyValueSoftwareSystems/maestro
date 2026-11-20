#!/usr/bin/env bash
# Install Maestro into a project, for Claude Code.
#   bash /path/to/maestro/install.sh [project-dir] [--force-workflows]
# Run it again to upgrade. Skills, commands and stacks are replaced. Your workflows are kept
# unless you pass --force-workflows. .maestro/workspace.yaml and your runs are never touched.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="."
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force-workflows) FORCE=1 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) DEST="$arg" ;;
  esac
done
DEST="$(cd "$DEST" && pwd)"
if [ "$SRC" = "$DEST" ]; then
  echo "Point this at the project you want to install into, not the Maestro repo." >&2
  exit 1
fi

copy_dir() { rm -rf "$2"; mkdir -p "$(dirname "$2")"; cp -R "$1" "$2"; }

# The lead, agent and sub-skill skills, plus the slash commands. Always replaced.
for skill in "$SRC"/skills/*/ "$SRC"/skills/agents/*/; do
  [ -f "$skill/SKILL.md" ] || continue
  copy_dir "${skill%/}" "$DEST/.claude/skills/$(basename "$skill")"
done
mkdir -p "$DEST/.claude/commands"
cp "$SRC"/commands/*.md "$DEST/.claude/commands/"

# The stack skill library. /maestro-init copies the matching stacks into .claude/skills,
# and an upgrade refreshes the copies that are already there.
copy_dir "$SRC/stacks" "$DEST/.maestro/stacks"
for stack in "$SRC"/stacks/*/; do
  name="$(basename "$stack")"
  if [ -d "$DEST/.claude/skills/$name" ]; then
    copy_dir "${stack%/}" "$DEST/.claude/skills/$name"
  fi
done

# Workflows are yours to edit, so existing files are kept unless --force-workflows.
(cd "$SRC/workflows" && find . -name '*.yaml') | while read -r f; do
  target="$DEST/.maestro/workflows/${f#./}"
  if [ "$FORCE" = 1 ] || [ ! -e "$target" ]; then
    mkdir -p "$(dirname "$target")"
    cp "$SRC/workflows/$f" "$target"
  else
    echo "kept your .maestro/workflows/${f#./}"
  fi
done

# Worktrees are local only, so keep them out of git.
touch "$DEST/.gitignore"
grep -qxF '.maestro/worktrees/' "$DEST/.gitignore" || echo '.maestro/worktrees/' >> "$DEST/.gitignore"

echo "Maestro installed in $DEST"
echo "Next, in Claude Code: /maestro-init  (finds repos and stacks, and builds the knowledge base)"
