#!/usr/bin/env bash
# =============================================================================
# install.sh — install the Maestro pack (KeyValue AI-SDLC v2) into your project
# =============================================================================
# Run this from the ROOT of your main repo. It:
#   1. installs OUR skills + commands + agents into your AI-harness config dirs
#      (.claude/, .cursor/, and/or .agents/)
#   2. copies the engine + workflows + builder UI into your repo
#      (runtime files the Maestro skill shells out to)
#
# That's it — no CLI, no config file, no daemons. Everything runs inside your
# interactive session via the Maestro skill; the engine is stdlib-only python3.
#
# Two ways to run — no clone required either way:
#   • Piped: curl -fsSL https://raw.githubusercontent.com/KeyValueSoftwareSystems/maestro/main/install.sh \
#              | bash -s -- claude-code cursor codex hermes
#   • From a checkout: /path/to/maestro/install.sh claude-code
#
# Bare words are harness targets: claude-code (default), cursor, codex and/or hermes.
# codex and hermes share .agents/skills (the Agent Skills project folder both read).
#
# Stack filter (optional):
#   --stack go,react   install core SDLC skills/agents + ONLY those tagged stack:go /
#                      stack:react. Repeatable and comma-separated. `--stack all` (or no
#                      flag) installs everything. Items with no `stack:` tag are CORE and
#                      always installed. /maestro-init passes this automatically after
#                      detecting your repo's stack.
#
# Upgrades (re-run) never overwrite a workflow or skill you edited: stock copies are replaced,
# edited ones are kept and the new upstream version lands beside them as
# .maestro/workflows/<name>.upstream (engine/install_workflows.py) or <skill>/<file>.upstream
# (engine/install_skills.py).
#   --dry-run          print the workflow upgrade plan and exit without writing anything
#
# Version pinning: the installed version is recorded in .maestro/install.json. A re-run
# without --ref installs that same version again (reproducible); pass --ref to move.
#   --ref <tag|sha|branch>   install exactly this version (e.g. --ref v1.4.0, --ref main)
#
# Env overrides:
#   MAESTRO_REPO     pack's GitHub slug      (default KeyValueSoftwareSystems/maestro)
#   MAESTRO_REF      git ref for the tarball (default: --ref, else the recorded one, else main)
#   DEST             where to copy runtime   (default: current directory)
# =============================================================================
set -uo pipefail   # not -e: one failed skill install must not abort the rest

REPO="${MAESTRO_REPO:-KeyValueSoftwareSystems/maestro}"
REF="${MAESTRO_REF:-}"
DEST="${DEST:-$PWD}"

AGENTS=""
STACKS=""              # empty => install everything (back-compat)
DRY_RUN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --stack)   shift; STACKS="$STACKS ${1:-}" ;;
    --stack=*) STACKS="$STACKS ${1#*=}" ;;
    --dry-run) DRY_RUN=1 ;;
    --ref)     shift; REF="${1:-}" ;;
    --ref=*)   REF="${1#*=}" ;;
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
copy_skills() { # $1 = dst dir, $2 = host name — filtered by --stack
  # SOURCE is organized into category folders (skills/core/…, skills/stacks/<x>/…,
  # skills/maestro); the INSTALLED tree is intentionally FLAT — one dir per skill keyed
  # by its frontmatter name, which is the only identity workflows/harness discovery use.
  # So we find every SKILL.md at any depth and flatten each skill dir into $1/. An edited
  # installed skill is kept (engine/install_skills.py); its new version lands as *.upstream.
  #
  # $1 must already be a real directory. Template workspaces link each
  # workspace-* skill from .claude/skills and .cursor/skills into skills/.
  # Maestro's copies are written beside those links. A directory symlink is
  # refused so the installer never writes into skills/.
  local dst="$1"
  if [ -L "$dst" ]; then
    echo "FAIL: $dst is a symlink. Link each template skill from a real directory into skills/." >&2
    exit 1
  fi
  mkdir -p "$(dirname "$dst")"
  mkdir -p "$dst"
  kept=0; skipped=0
  list="$(mktemp)"
  while IFS= read -r skillmd; do
    d="$(dirname "$skillmd")"
    if want_item "$skillmd"; then printf '%s\n' "$d" >> "$list"; kept=$((kept+1))
    else skipped=$((skipped+1)); fi
  done < <(find "$SRC/skills" -name SKILL.md -type f | sort)
  if command -v python3 >/dev/null 2>&1; then
    python3 "$SRC/engine/install_skills.py" --dst "$dst" --host "$2" \
      --manifest "$DEST/.maestro/skill-manifest.json" --skills-from "$list"
  else
    while IFS= read -r d; do cp -R "$d" "$dst/"; done < "$list"
  fi
  rm -f "$list"
  note "skills -> $dst ($kept selected, $skipped skipped by --stack)"
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
remove_retired_skills() { # $1 = installed skills dir
  # Named migrations only: never prune the directory wholesale because it may contain
  # user-authored or third-party skills. `brainstorm` was replaced by the bounded
  # `prd-interview` + `prd-writing` pair; the per-stack design/tasks/implement/review skills,
  # `plan`, `repo-design` and `verify` were folded into the repo-* and *-writing skills and
  # the engine's verify step.
  for retired in brainstorm plan repo-design verify run-upgrade-repair design-correction-fold \
      backend-design frontend-design backend-tasks frontend-tasks \
      backend-implement frontend-implement backend-review frontend-review; do
    target="$1/$retired"
    if [ -d "$target" ]; then
      rm -rf -- "$target"
      note "removed retired skill -> $target"
    fi
  done
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
if [ -z "$REF" ] && [ -f "$DEST/.maestro/install.json" ] && command -v python3 >/dev/null 2>&1; then
  # reproducible re-runs: reinstall the recorded version unless --ref asks for another
  REF="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("ref") or "")' \
    "$DEST/.maestro/install.json" 2>/dev/null || true)"
fi
[ -n "$REF" ] || REF="main"
if [ -z "$SRC" ]; then
  say "Fetching $REPO@$REF …"
  tmp="$(mktemp -d)"
  CLEANUP="$tmp"
  # codeload resolves a branch, a tag or a commit sha for the same URL
  if curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" | tar -xz -C "$tmp" 2>/dev/null; then
    SRC="$(find "$tmp" -maxdepth 1 -mindepth 1 -type d | head -1)"
  fi
  [ -n "$SRC" ] && [ -f "$SRC/engine/maestroctl.py" ] || {
    echo "could not fetch $REPO@$REF — is the repo private or the ref wrong?" >&2
    echo "  private repo? clone it and run ./install.sh from the checkout instead." >&2
    exit 1
  }
fi
trap '[ -n "$CLEANUP" ] && rm -rf "$CLEANUP"' EXIT

if [ -n "$DRY_RUN" ]; then
  say "Dry run — $REPO workflows vs $DEST/.maestro/workflows"
  python3 "$SRC/engine/install_workflows.py" --src "$SRC/workflows" --root "$DEST" --dry-run
  exit $?
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
      copy_skills        "$DEST/.claude/skills" claude-code
      remove_retired_skills "$DEST/.claude/skills"
      copy_tree commands "$DEST/.claude/commands"
      copy_agents        "$DEST/.claude/agents"
      ;;
    cursor)
      say "Installing skills + commands for Cursor${STACKS:+ (stacks: $STACKS)}"
      copy_skills        "$DEST/.cursor/skills" cursor
      remove_retired_skills "$DEST/.cursor/skills"
      copy_tree commands "$DEST/.cursor/commands"
      # Cursor has no subagent registry; the Maestro skill degrades to inline mode.
      ;;
    codex|hermes)
      # Codex (`$skill-name`) and Hermes Agent (`/skill-name`, after `hermes skills trust`)
      # both discover repository skills from .agents/skills; their native subagents need no
      # copied Claude agent definitions. One copy serves both, recorded as host `codex`.
      if [ -n "${AGENTS_SKILLS_DONE:-}" ]; then continue; fi
      AGENTS_SKILLS_DONE=1
      say "Installing skills for Codex / Hermes Agent (.agents/skills)${STACKS:+ (stacks: $STACKS)}"
      copy_skills        "$DEST/.agents/skills" codex
      remove_retired_skills "$DEST/.agents/skills"
      ;;
    *) echo "  unknown IDE target: $agent (skipping)" >&2 ;;
  esac
done

# ---------------------------------------------------------------- 2. runtime files
# Everything Maestro ships lives under a single .maestro/ parent to keep the consumer
# repo root clean and avoid colliding with the repo's own engine/ docs/ ui/ dirs:
#   .maestro/engine  .maestro/ui       — regenerated runtime (gitignore)
#   .maestro/workflows  .maestro/docs  — committed, customize freely
#   .maestro/index   .maestro/memory  .maestro/runs/<slug>/ — sync plans / memory / run state
#   docs/provenance.yaml — shared living-doc provenance (written by record-knowledge)
#   .maestro/workflow-manifest.json  — committed: what the last upgrade offered per workflow
say "Copying runtime into $DEST/.maestro"
mkdir -p "$DEST/.maestro/workflows" "$DEST/.maestro/engine" "$DEST/.maestro/ui" "$DEST/.maestro/docs"
cp -R "$SRC/engine/." "$DEST/.maestro/engine/" && note ".maestro/engine/ (stdlib-only python3)"
rm -rf "$DEST/.maestro/engine/tests" "$DEST/.maestro/engine/__pycache__" 2>/dev/null
# Workflows are user-editable: upgrade them file by file, never over a local edit.
if command -v python3 >/dev/null 2>&1; then
  python3 "$SRC/engine/install_workflows.py" --src "$SRC/workflows" --root "$DEST"
else
  echo "  python3 not found — workflows NOT installed/upgraded (the engine needs python3)" >&2
fi
cp "$SRC/ui/builder.html" "$DEST/.maestro/ui/builder.html" && note ".maestro/ui/builder.html (visual workflow builder)"
cp "$SRC/docs/workflow-spec.md" "$DEST/.maestro/docs/workflow-spec.md" 2>/dev/null && note ".maestro/docs/workflow-spec.md"
# The repo-local dev wrapper + a copy of this installer, so `./maestro ui` and
# `./maestro install` work without re-fetching. The wrapper never writes run state.
cp "$SRC/bin/maestro" "$DEST/maestro" && chmod +x "$DEST/maestro" && note "maestro (dev wrapper: ui + install)"
cp "$SRC/install.sh" "$DEST/install.sh" 2>/dev/null && note "install.sh (re-run to upgrade)"

# Record what was installed, so a re-run reproduces it and support can tell versions apart.
SRC_COMMIT=""
if git -C "$SRC" rev-parse HEAD >/dev/null 2>&1; then SRC_COMMIT="$(git -C "$SRC" rev-parse HEAD)"; fi
if command -v python3 >/dev/null 2>&1; then
  python3 - "$DEST/.maestro/install.json" "$REF" "$SRC_COMMIT" "$REPO" "$AGENTS" "$STACKS" <<'PY'
import datetime, json, sys
path, ref, commit, repo, hosts, stacks = sys.argv[1:7]
json.dump({"schema_version": 1, "repo": repo, "ref": ref, "commit": commit or None,
           "hosts": hosts.split(), "stacks": stacks.split(),
           "installed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
          open(path, "w"), indent=2)
PY
  note ".maestro/install.json (installed version: $REF${SRC_COMMIT:+ @ ${SRC_COMMIT:0:12}})"
fi

say "Done."
case " $AGENTS " in
  *" codex "*)
    note 'Codex: open the repo and invoke  $maestro-init  (detect stack + build the knowledge base)'
    note 'Codex: then start a feature with $maestro my-feature'
    ;;
esac
case " $AGENTS " in
  *" hermes "*)
    note 'Hermes Agent: run  hermes skills trust  in the repo, then  /maestro-init  and  /maestro my-feature'
    ;;
esac
case " $AGENTS " in
  *" claude-code "*|*" cursor "*)
    note "Claude Code / Cursor: run  /maestro-init  then  /maestro my-feature"
    ;;
esac
note "Guide: ./maestro help   (getting started, .gitignore, upgrade/uninstall)"
