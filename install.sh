#!/usr/bin/env bash
# install.sh — install Maestro into the current project.
#
#   curl -fsSL https://raw.githubusercontent.com/KeyValueSoftwareSystems/maestro/main/install.sh \
#     | bash -s -- claude-code [codex] [cursor] [--ref <tag|branch>]
#   /path/to/maestro/install.sh claude-code          # from a checkout
#
# Targets (default claude-code):
#   claude-code  skills → .claude/skills/   subagents → .claude/agents/
#   codex        skills → .agents/skills/   (also read by Hermes)
#   cursor       skills → .cursor/skills/
# All targets: default workflows → .maestro/defaults/workflows/
#
# Upgrades: a file you edited is kept; the new version is written beside it as <file>.upstream.
# Your own workflows and templates go in .maestro/workflows/ and .maestro/templates/; the
# installer never touches those.
set -euo pipefail

REPO="${MAESTRO_REPO:-KeyValueSoftwareSystems/maestro}"
REF="${MAESTRO_REF:-main}"
DEST="${DEST:-$PWD}"
TARGETS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) shift; REF="$1" ;;
    --ref=*) REF="${1#*=}" ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *) TARGETS+=("$1") ;;
  esac
  shift
done
[ ${#TARGETS[@]} -gt 0 ] || TARGETS=(claude-code)

# --- source: this checkout, or a downloaded tarball --------------------------------------------
SRC=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [ -d "$here/agents" ] && [ -d "$here/skills" ] && SRC="$here"
fi
if [ -z "$SRC" ]; then
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" | tar -xz -C "$tmp"
  SRC="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
fi

MANIFEST="$DEST/.maestro/install-manifest"
mkdir -p "$DEST/.maestro"
touch "$MANIFEST"
NEW_MANIFEST="$(mktemp)"

hash_of() { sha256sum "$1" | cut -d' ' -f1; }

# install_file <src> <dest>: replace stock copies, keep edited ones (write <dest>.upstream).
install_file() {
  local src="$1" dst="$2" rel="${2#$DEST/}" recorded current new
  new="$(hash_of "$src")"
  mkdir -p "$(dirname "$dst")"
  if [ -f "$dst" ]; then
    current="$(hash_of "$dst")"
    recorded="$(awk -v p="$rel" '$2==p {print $1}' "$MANIFEST")"
    if [ "$current" != "$new" ] && [ -n "$recorded" ] && [ "$current" != "$recorded" ]; then
      cp "$src" "$dst.upstream"
      echo "  kept your edits: $rel (new version: $rel.upstream)"
      echo "$recorded $rel" >> "$NEW_MANIFEST"
      return
    fi
  fi
  cp "$src" "$dst"
  echo "$new $rel" >> "$NEW_MANIFEST"
}

install_tree() { # <src dir> <dest dir>
  local f
  while IFS= read -r f; do install_file "$1/$f" "$2/$f"; done \
    < <(cd "$1" && find . -type f | sed 's|^\./||' | sort)
}

install_skills() { # <dest skills dir>
  local d
  for d in "$SRC"/agents/*/ "$SRC"/skills/*/; do
    install_tree "${d%/}" "$1/$(basename "$d")"
  done
}

for t in "${TARGETS[@]}"; do
  case "$t" in
    claude-code)
      echo "Claude Code:"
      install_skills "$DEST/.claude/skills"
      install_tree "$SRC/adapters/claude-code/agents" "$DEST/.claude/agents" ;;
    codex|hermes)
      echo "Codex / Hermes:"
      install_skills "$DEST/.agents/skills" ;;
    cursor)
      echo "Cursor:"
      install_skills "$DEST/.cursor/skills" ;;
    *) echo "unknown target: $t (use claude-code, codex, cursor)" >&2; exit 2 ;;
  esac
done
install_tree "$SRC/workflows" "$DEST/.maestro/defaults/workflows"
mkdir -p "$DEST/.maestro/workflows" "$DEST/.maestro/templates"

sort -u -k2,2 "$NEW_MANIFEST" > "$MANIFEST"; rm -f "$NEW_MANIFEST"
echo "$REF" > "$DEST/.maestro/version"

cat <<'EOF'

Maestro installed.
  Run a workflow:   /maestro major "<what to build>"   (also: minor, bugfix)
  Use one agent:    /designer, /brew, /reviewer, /litmus, /sherlock
  Customise:        copy a file from .maestro/defaults/workflows/ to .maestro/workflows/ and edit it
EOF
