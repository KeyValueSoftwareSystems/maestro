---
description: Run or resume a Maestro workflow for a feature slug
argument-hint: <slug or feature request> [workflow-file] [key=value ...] [--mode human|design|auto] [--debug]
---

Load and follow the `maestro` skill (the Maestro lead agent) with these arguments: $ARGUMENTS

The first argument is the feature slug (or a feature request); an optional second argument is the
workflow file (default `.maestro/workflows/sdlc-main.yaml`); remaining `key=value` pairs are
workflow inputs. `--mode` sets the run mode and `--debug` records a timing profile.
