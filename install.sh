#!/usr/bin/env bash
# =============================================================================
# install.sh — install the Maestro pack (KeyValue AI-SDLC v2) into your project
# =============================================================================
# Run this from the ROOT of your main repo. It:
#   1. installs OUR skills + commands + agents into your AI-IDE config dirs
#      (.claude/ and/or .cursor/ — skills, commands, agents)
#   2. installs the external helper skills the flow delegates to (Superpowers)
#   3. copies the engine + workflows + builder UI into your repo
#      (runtime files the /maestro skill shells out to)
#
# That's it — no CLI, no config file, no daemons. Everything runs inside your
# interactive session via the /maestro skill; the engine is stdlib-only python3.
#
# Two ways to run — no clone required either way:
#   • Piped: curl -fsSL https://raw.githubusercontent.com/KeyValueSoftwareSystems/kv-skills/main/install.sh \
#              | bash -s -- claude-code cursor
#   • From a checkout: /path/to/kv-skills/install.sh claude-code
#
# Bare words are IDE targets: claude-code (default) and/or cursor.
#
# Stack filter (optional):
#   --stack go,react   install core SDLC skills/agents + ONLY those tagged stack:go /
#                      stack:react. Repeatable and comma-separated. `--stack all` (or no
#                      flag) installs everything. Items with no `stack:` tag are CORE and
#                      always installed. /maestro-init passes this automatically after
#                      detecting your repo's stack.
#
# Env overrides:
#   KV_SKILLS_REPO   pack's GitHub slug      (default KeyValueSoftwareSystems/kv-skills)
#   KV_SKILLS_REF    git ref for the tarball (default main)
#   DEST             where to copy runtime   (default: current directory)
# =============================================================================
set -uo pipefail   # not -e: one failed skill install must not abort the rest

REPO="${KV_SKILLS_REPO:-KeyValueSoftwareSystems/kv-skills}"
REF="${KV_SKILLS_REF:-main}"
DEST="${DEST:-$PWD}"

AGENTS=""
STACKS=""              # empty => install everything (back-compat)
while [ $# -gt 0 ]; do
  case "$1" in
    --stack)   shift; STACKS="$STACKS ${1:-}" ;;
    --stack=*) STACKS="$STACKS ${1#*=}" ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *)  AGENTS="$AGENTS $1" ;;
  esac
  shift
done
AGENTS="${AGENTS# }"
[ -n "$AGENTS" ] || AGENTS="claude-code"
# normalise the stack filter: commas -> spaces, collapse whitespace, `all` clears it
STACKS="$(printf '%s' "$STACKS" | tr ',' ' ')"
STACKS="$(echo $STACKS)"
case " $STACKS " in *" all "*) STACKS="" ;; esac

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }

# --- stack filtering -------------------------------------------------------
# Stack tokens declared on an item's frontmatter `tags:` line, e.g. "go react".
# Empty output => the item is stack-agnostic CORE and is always installed.
frontmatter_stacks() { # $1 = .md file
  grep -m1 '^tags:' "$1" 2>/dev/null \
    | grep -oE 'stack:[A-Za-z0-9_+-]+' \
    | sed 's/^stack://' \
    | tr '\n' ' '
}
# want_item <md-file> — true if this item should be installed under the current filter.
want_item() {
  [ -z "$STACKS" ] && return 0                     # no filter -> everything
  st="$(frontmatter_stacks "$1")"
  [ -z "$st" ] && return 0                          # core -> always
  for s in $st; do
    for w in $STACKS; do
      [ "$s" = "$w" ] && return 0
    done
  done
  return 1
}
copy_skills() { # $1 = dst dir — filtered by --stack
  mkdir -p "$1"; kept=0; skipped=0
  for d in "$SRC"/skills/*/; do
    [ -f "$d/SKILL.md" ] || continue
    # strip the trailing slash: `cp -R foo/ dst/` copies CONTENTS on BSD cp; we want the dir
    if want_item "$d/SKILL.md"; then cp -R "${d%/}" "$1/" && kept=$((kept+1))
    else skipped=$((skipped+1)); fi
  done
  note "skills -> $1 ($kept installed, $skipped skipped by --stack)"
}
copy_agents() { # $1 = dst dir — filtered by --stack
  mkdir -p "$1"; kept=0; skipped=0
  for f in "$SRC"/agents/*.md; do
    [ -f "$f" ] || continue
    if want_item "$f"; then cp "$f" "$1/" && kept=$((kept+1))
    else skipped=$((skipped+1)); fi
  done
  note "agents -> $1 ($kept installed, $skipped skipped by --stack)"
}

# ---------------------------------------------------------------- source dir
# From a REAL checkout: use the files next to this script. Piped (curl | bash): fetch the
# tarball. The distinction is BASH_SOURCE[0] — it is set only when bash reads the script
# from a file, and unset when the script comes from stdin. Relying on $0 here was the bug:
# piped, $0 is "bash", dirname -> ".", so an already-installed repo looked like a checkout
# and every re-run/upgrade silently copied that repo onto itself instead of fetching.
SRC=""
CLEANUP=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
  if [ -n "$script_dir" ] && [ -f "$script_dir/engine/maestroctl.py" ]; then
    SRC="$script_dir"
  fi
fi
if [ -z "$SRC" ]; then
  say "Fetching $REPO@$REF …"
  tmp="$(mktemp -d)"
  CLEANUP="$tmp"
  if curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$REF" | tar -xz -C "$tmp" 2>/dev/null; then
    SRC="$(find "$tmp" -maxdepth 1 -mindepth 1 -type d | head -1)"
  fi
  [ -n "$SRC" ] && [ -f "$SRC/engine/maestroctl.py" ] || {
    echo "could not fetch $REPO@$REF — is the repo private or the ref wrong?" >&2
    echo "  private repo? clone it and run ./install.sh from the checkout instead." >&2
    exit 1
  }
fi
trap '[ -n "$CLEANUP" ] && rm -rf "$CLEANUP"' EXIT

# Guard the dev-in-pack-repo case: running the installer from inside the kv-skills checkout
# with DEST defaulting to that same checkout would copy files onto themselves and (worse)
# delete the source engine/tests. Detect same-dir and skip the runtime copy.
SAME_TREE=0
if [ "$(cd "$SRC" && pwd -P)" = "$(cd "$DEST" && pwd -P)" ]; then
  SAME_TREE=1
fi

# ---------------------------------------------------------------- 1. skills/commands/agents
copy_tree() { # copy_tree <src-subdir> <dst-dir>
  mkdir -p "$2"
  cp -R "$SRC/$1/." "$2/" && note "$1 -> $2"
}
for agent in $AGENTS; do
  case "$agent" in
    claude-code)
      say "Installing skills + commands + agents for Claude Code${STACKS:+ (stacks: $STACKS)}"
      copy_skills        "$DEST/.claude/skills"
      copy_tree commands "$DEST/.claude/commands"
      copy_agents        "$DEST/.claude/agents"
      ;;
    cursor)
      say "Installing skills + commands for Cursor${STACKS:+ (stacks: $STACKS)}"
      copy_skills        "$DEST/.cursor/skills"
      copy_tree commands "$DEST/.cursor/commands"
      # Cursor has no subagent registry; the /maestro skill degrades to inline mode.
      ;;
    *) echo "  unknown IDE target: $agent (skipping)" >&2 ;;
  esac
done

# ---------------------------------------------------------------- 2. external skills
say "Installing external helper skills (Superpowers)"
if command -v npx >/dev/null 2>&1; then
  for s in brainstorming writing-plans test-driven-development requesting-code-review \
           systematic-debugging using-git-worktrees; do
    for agent in $AGENTS; do
      npx -y skills add obra/superpowers --skill "$s" -a "$agent" -y >/dev/null 2>&1 \
        && note "$s ($agent)" || note "SKIPPED $s ($agent) — install later: npx skills add obra/superpowers --skill $s -a $agent"
    done
  done
else
  note "npx not found — skipping. The flow still works; skills fall back to inline behavior."
  note "Install later with: npx skills add obra/superpowers --skill <name> -a <ide>"
fi

# ---------------------------------------------------------------- 3. runtime files
if [ "$SAME_TREE" = "1" ]; then
  say "Runtime copy skipped — installing inside the kv-skills checkout itself (source == dest)."
else
  say "Copying runtime into $DEST"
  mkdir -p "$DEST/workflows" "$DEST/engine" "$DEST/ui" "$DEST/docs"
  cp -R "$SRC/engine/." "$DEST/engine/" && note "engine/ (stdlib-only python3)"
  rm -rf "$DEST/engine/tests" "$DEST/engine/__pycache__" 2>/dev/null
  cp -R "$SRC/workflows/." "$DEST/workflows/" && note "workflows/ (example pack — customize freely)"
  cp "$SRC/ui/builder.html" "$DEST/ui/builder.html" && note "ui/builder.html (visual workflow builder)"
  cp "$SRC/docs/workflow-spec.md" "$DEST/docs/workflow-spec.md" 2>/dev/null && note "docs/workflow-spec.md"
  # The repo-local dev wrapper + a copy of this installer, so `./maestro ui` and
  # `./maestro install` work without re-fetching. The wrapper never writes run state.
  cp "$SRC/bin/maestro" "$DEST/maestro" && chmod +x "$DEST/maestro" && note "maestro (dev wrapper: ui + install)"
  cp "$SRC/install.sh" "$DEST/install.sh" 2>/dev/null && note "install.sh (re-run to upgrade)"
fi

say "Done."
cat <<'EOF'
  Get started — open your IDE (Claude Code / Cursor) in this repo and run:

    /maestro my-feature              # runs workflows/sdlc-main.yaml, resumable
                                     # (scaffolds .maestro/my-feature/requirement/
                                     #  on first run and asks you to fill it)

  Design workflows visually: ./maestro ui   (serves the builder, auto-loads your runs;
                             --port to change the port) — or open ui/builder.html directly.
  Re-install / add an IDE:   ./maestro install [claude-code|cursor]
  Lint one by hand:          python3 engine/maestroctl.py validate <file>

  Version control — recommended .gitignore for a consumer repo:
    .claude/skills/      .claude/commands/      .claude/agents/
    .cursor/skills/      .cursor/commands/
    engine/  ui/  maestro  install.sh   # regenerated by re-running install.sh
  COMMIT these (they are your feature's source of truth and resume ledger):
    workflows/   docs/workflow-spec.md   .maestro/<slug>/
  One run ledger per feature slug — see "Working as a team" in the README before
  two people drive the same slug.

  Upgrade later: re-run the same curl | bash command (it re-fetches and overwrites).
  Uninstall: delete the dirs listed above; .maestro/<slug>/ holds your work — keep it.
EOF
