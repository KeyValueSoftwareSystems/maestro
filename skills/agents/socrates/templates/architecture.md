---
source_commit: {<repo>: <sha>}
---
# Architecture

<Three to five sentences: what the system does, for whom, and its main parts. Then which domain
doc to open for which kind of change.>

## Repositories
| Repo | Purpose | Stack (with versions) | Entry points | Agent guide |
|---|---|---|---|---|
| <name> | <one line> | <e.g. Node 24, NestJS 11> | <`path`> | <AGENTS.md or CLAUDE.md path, or none> |

## Commands
| Repo | Install | Run locally | All tests | One test file | Lint and typecheck |
|---|---|---|---|---|---|

Tests need: <env var names and services; never values>

## How the parts talk
| From | To | How (HTTP, queue, DB, ...) | What for | Contract (file) |
|---|---|---|---|---|

<Optional: a mermaid diagram of this table only.>

## Data
| Store | Written by | Main entities | Schema or migrations |
|---|---|---|---|

## Domains
| Domain | Doc | Summary |
|---|---|---|
| <name> | [domains/<name>.md](domains/<name>.md) | <one line> |

## Cross-cutting
| Concern | How it works | Code |
|---|---|---|
| Auth | | |
| Config and secrets | | |
| Logging and errors | | |
| Build and deploy | | |

## Decisions
| ID | Decision | Why | Rejected alternative | Source | Status |
|---|---|---|---|---|---|
| D1 | | | | <ADR, PR, commit or file> | <active / superseded by D<n>> |

## Gotchas
- <what misleads or breaks, and why> (`path` `symbol`, learned <YYYY-MM-DD>)
