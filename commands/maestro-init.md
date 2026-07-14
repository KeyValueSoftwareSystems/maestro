---
description: Onboard a repo — detect its stack, install matching skills/agents, build the knowledge base
argument-hint: "[claude-code|cursor ...]"
---

Load and follow the `maestro-init` skill with these arguments: $ARGUMENTS

Optional arguments are IDE targets to install for (`claude-code` and/or `cursor`); if
omitted, the skill infers them from the `.claude/` / `.cursor/` dirs present. The skill
runs `detect-stack` (detect the tech stack and install the matching stack-tagged skills +
agents) and then `build-knowledge` (write the living-docs knowledge base).
