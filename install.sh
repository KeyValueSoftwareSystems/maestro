#!/usr/bin/env bash
# =============================================================================
# install.sh — install the KeyValue AI-SDLC pack into your project
# =============================================================================
# Run this from the ROOT of your main repo. It:
#   1. installs OUR skills          (npx skills add KeyValueSoftwareSystems/kv-skills)
#   2. installs the external skills the flow uses, one by one (npx skills add ...)
#   3. copies the Conductor workflows + config into your repo
#      (+ installs the `maestro <slug>` run wrapper on PATH)
#   4. installs Conductor (optional — needs `uv`; skip with --no-conductor)
#
# Two ways to run — no clone required either way:
#   • Piped (no clone): fetches the workflows/config from the repo tarball itself.
#       curl -fsSL https://raw.githubusercontent.com/KeyValueSoftwareSystems/kv-skills/main/install.sh \
#         | bash -s -- claude-code cursor
#   • From a checkout: copies the workflows/config sitting next to this script.
#       /path/to/kv-skills/install.sh claude-code
#
# Bare words are IDE/agent names (default: claude-code). Flags: --no-conductor.
#
# Env overrides:
#   KV_SKILLS_REPO   our pack's GitHub slug   (default KeyValueSoftwareSystems/kv-skills)
#   KV_SKILLS_REF    git ref for the tarball  (default main)
#   DEST             where to copy workflows  (default: current directory)
# =============================================================================
set -uo pipefail   # not -e: one failed skill install must not abort the rest

REPO="${KV_SKILLS_REPO:-KeyValueSoftwareSystems/kv-skills}"
REF="${KV_SKILLS_REF:-main}"
DEST="${DEST:-$PWD}"

# Parse args: bare words are IDE/agent names; --no-conductor skips step 4.
INSTALL_CONDUCTOR=1
AGENTS=""
for a in "$@"; do
  case "$a" in
    --no-conductor) INSTALL_CONDUCTOR=0 ;;
    -*) echo "unknown flag: $a" >&2; exit 2 ;;
    *)  AGENTS="$AGENTS $a" ;;
  esac
done
[ -n "$AGENTS" ] || AGENTS="claude-code"          # default IDE
AFLAGS=""; for ag in $AGENTS; do AFLAGS="$AFLAGS -a $ag"; done

command -v npx >/dev/null 2>&1 || { echo "npx (Node.js) is required." >&2; exit 1; }

# Locate the pack files (workflows/ + skills.config.yaml). Use the checkout we're
# running from if there is one; otherwise download the repo tarball — no clone.
CLEANUP=""
SELF="${BASH_SOURCE[0]:-}"
if [ -n "$SELF" ] && [ -f "$SELF" ] && [ -d "$(dirname "$SELF")/workflows" ]; then
  SRC="$(cd "$(dirname "$SELF")" && pwd)"
else
  command -v curl >/dev/null 2>&1 || { echo "curl required for no-clone install." >&2; exit 1; }
  command -v tar  >/dev/null 2>&1 || { echo "tar required for no-clone install." >&2; exit 1; }
  CLEANUP="$(mktemp -d)"
  echo "==> Downloading pack ($REPO@$REF)"
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" | tar -xz -C "$CLEANUP" \
    || { echo "could not download $REPO@$REF — set KV_SKILLS_REPO/KV_SKILLS_REF." >&2; rm -rf "$CLEANUP"; exit 1; }
  SRC="$(cd "$CLEANUP"/*/ && pwd)"                # the single extracted top dir
fi

echo "==> Installing skills for:$AFLAGS"

# 1) our skills
echo "--> $REPO (our skills)"
npx skills add "$REPO" --skill '*' $AFLAGS -y </dev/null \
  || echo "WARN: could not install $REPO (published? set KV_SKILLS_REPO)"

# 2) external skills the default flow uses (Superpowers pack, MIT — installed from source)
EXTERNAL_SKILLS="
brainstorming
writing-plans
test-driven-development
requesting-code-review
systematic-debugging
using-git-worktrees
"
for s in $EXTERNAL_SKILLS; do
  echo "--> obra/superpowers --skill $s"
  npx skills add obra/superpowers --skill "$s" $AFLAGS -y </dev/null \
    || echo "WARN: failed to install external skill: $s"
done

# 3) copy the Conductor workflows + config into the target repo (idempotent — no nesting)
echo "==> Copying workflows + config into $DEST"
mkdir -p "$DEST/workflows"
cp -R "$SRC/workflows/."         "$DEST/workflows/"
cp    "$SRC/skills.config.yaml"  "$DEST/skills.config.yaml"

# keep regenerable run output out of git
if [ -f "$DEST/.gitignore" ] && ! grep -q '^\.sdlc/' "$DEST/.gitignore" 2>/dev/null; then
  printf '\n# KeyValue AI-SDLC run output (regenerable)\n.sdlc/\n.kv/\n' >> "$DEST/.gitignore"
fi

# 3b) install the slug-only run wrapper (maestro <slug>) on PATH — same dir uv
#     uses for `conductor`, so it's already on PATH when Conductor is installed.
BIN_DIR="${KV_BIN_DIR:-$HOME/.local/bin}"
if [ -f "$SRC/bin/maestro" ]; then
  mkdir -p "$BIN_DIR"
  cp "$SRC/bin/maestro" "$BIN_DIR/maestro" && chmod +x "$BIN_DIR/maestro" \
    && echo "==> Installed maestro -> $BIN_DIR/maestro" \
    || echo "WARN: could not install maestro wrapper into $BIN_DIR"
  case ":$PATH:" in
    *":$BIN_DIR:"*) : ;;
    *) echo "    NOTE: $BIN_DIR is not on your PATH — add it to use \`maestro\`." ;;
  esac
fi

# 4) Conductor (optional)
if [ "$INSTALL_CONDUCTOR" = 1 ]; then
  # Conductor is a uv tool. If uv is missing, install it first (the maestro wrapper
  # is useless without conductor on PATH) — official astral-sh installer, into the
  # same ~/.local/bin we already put maestro in.
  if ! command -v uv >/dev/null 2>&1; then
    echo "==> 'uv' not found — installing it (astral-sh) so Conductor can be installed"
    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
      # Make uv usable for the rest of THIS script: source the env file the installer
      # writes, and prepend its bin dir to PATH as a fallback.
      UV_BIN="${XDG_BIN_HOME:-$HOME/.local/bin}"
      # shellcheck disable=SC1090
      [ -f "$UV_BIN/env" ] && . "$UV_BIN/env"
      case ":$PATH:" in *":$UV_BIN:"*) : ;; *) PATH="$UV_BIN:$PATH" ;; esac
    else
      echo "WARN: 'uv' install failed."
    fi
  fi

  if command -v uv >/dev/null 2>&1; then
    echo "==> Installing Conductor (with claude-agent-sdk)"
    uv tool install --force --with 'claude-agent-sdk>=0.1.0' \
      git+https://github.com/microsoft/conductor.git \
      || echo "WARN: Conductor install failed — install manually (see README)."
  else
    echo "==> Skipping Conductor: 'uv' unavailable. To run the workflows later, install"
    echo "    uv (https://docs.astral.sh/uv/getting-started/installation/), then:"
    echo "    uv tool install --force --with 'claude-agent-sdk>=0.1.0' git+https://github.com/microsoft/conductor.git"
  fi
fi

[ -n "$CLEANUP" ] && rm -rf "$CLEANUP"

cat <<EOF

Done. Next:
  • Slash commands (any IDE):  /hld  /design  /backend-impl  /qa  ...
  • Full pipeline, the easy way (from your repo root):
      mkdir -p features/saved-search && \$EDITOR features/saved-search/prd.md
      maestro saved-search                              # default pipeline (dashboard on :8080)
      maestro saved-search --path=workflows/design.yaml # or any individual/custom workflow
  • Full pipeline, explicit (Conductor):
      cd workflows && conductor validate main.yaml
      conductor run main.yaml --web \\
        --input feature="Add saved-search" --input feature_slug="saved-search"
  • Swap any behavior by editing skills.config.yaml (one file, everywhere).
  • Set the default model / web port in workflows/maestro.config.yaml (KV_MODEL_DEFAULT / KV_WEB_PORT).
EOF
