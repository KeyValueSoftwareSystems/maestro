---
description: Run or resume a Maestro workflow for a feature slug
argument-hint: <slug or feature request> [workflow-file] [path=major|minor] [key=value ...] [--mode human|design|auto] [--no-profile]
---

Load and follow the `maestro` skill (the Maestro lead agent) with these arguments: $ARGUMENTS

The first argument is the feature slug (or a feature request); an optional second argument is the
workflow file (default `.maestro/workflows/sdlc-main.yaml`); remaining `key=value` pairs are
workflow inputs. The default workflow needs `path=major` (full PRD and plan) or `path=minor` (mini
PRD and a short plan); when it is missing, ask the person which one — never guess. `--mode` sets the run mode and `--no-profile` skips the timing profile that is recorded by default.
