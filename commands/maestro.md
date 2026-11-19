---
description: Run or resume a Maestro workflow for a feature slug
argument-hint: <slug or feature request> [workflow-file | bugfix] [path=major|minor | branch=<b>] [key=value ...] [--mode human|design|auto] [--no-profile]
---

Load and follow the `maestro` skill (the Maestro lead agent) with these arguments: $ARGUMENTS

The first argument is the feature slug (or a feature request); an optional second argument is the
workflow file (default `.maestro/workflows/sdlc-main.yaml`; the short name `bugfix` means
`.maestro/workflows/bugfix.yaml`); remaining `key=value` pairs are workflow inputs. The default
workflow needs `path=major` (full PRD and plan) or `path=minor` (mini PRD and a short plan); the
`bugfix` workflow needs `branch=<the branch the bug is on>`. When the needed one is missing, ask
the person — never guess. `--mode` sets the run mode and `--no-profile` skips the timing profile that is recorded by default.
