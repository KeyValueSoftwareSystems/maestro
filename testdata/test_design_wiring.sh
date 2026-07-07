#!/usr/bin/env bash
# Verifies design.yaml guard/mark wiring against state.py, deterministically.
set -uo pipefail
cd "$(dirname "$0")/.."          # repo root
SLUG="wiring-test-$$"
STATE="python3 workflows/state.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

# Fresh slug: hld not done -> guard exits 1 (would route to author_hld)
$STATE check --slug "$SLUG" --step hld && fail "hld should be not-done on a fresh slug"

# Seed an artifact and mark hld done -> guard exits 0 (would route to hld_approval)
mkdir -p "docs/technical/$SLUG"
echo "# HLD" > "docs/technical/$SLUG/hld.md"
$STATE mark --slug "$SLUG" --step hld --artifact "docs/technical/$SLUG/hld.md" || fail "mark hld"
$STATE check --slug "$SLUG" --step hld || fail "hld should be done after mark"

# Cascade reset (revise route) clears hld + downstream
$STATE reset --slug "$SLUG" --step hld --step backend_lld --step frontend_lld --step api_contract || fail "reset"
$STATE check --slug "$SLUG" --step hld && fail "hld should be cleared after reset"

# Cleanup
rm -rf ".sdlc/$SLUG" "docs/technical/$SLUG"
echo "OK: design.yaml guard/mark/reset wiring verified"
