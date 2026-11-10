---
description: Onboard a repository newly added to the workspace after /maestro-init
argument-hint: ""
---

Load and follow the `maestro-sync` skill with these arguments: $ARGUMENTS

The skill adds a `maestro.config.yaml` entry for each repository newly cloned into
`codebase/`, detects only those repositories' stacks, fills their build/test commands,
installs matching stack skills, and writes those repositories' docs with build-knowledge
(codebase map, domain pages, architecture.md). It only adds: existing entries are never
changed or removed, and other repositories' docs are not refreshed.
