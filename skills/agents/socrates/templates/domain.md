---
source_commit: {<repo>: <sha>}
---
# <Domain>

<What this domain does for the business, in one or two sentences, and the repos and folders
that hold it.>

## Glossary
| ID | Term | Meaning | Name in code |
|---|---|---|---|
| <DOM>-GL-001 | <business word> | <one line> | <`symbol` or table, when it differs> |

## Key flows
<Only flows that cross modules or repos. One row per flow: three to five steps that name modules
or apps, not functions. No branches or error paths.>
| ID | Flow | Trigger | What happens | Code |
|---|---|---|---|---|
| <DOM>-KF-001 | <name> | <what starts it> | <step → step → step> | <`path` `symbol` of the entry point> |

## Business rules
<What the system does or allows, that the code can't show on its own, that a future change must
keep, and that something enforces. One rule per bullet.>
- <DOM>-BR-001: <the rule, in one sentence>
  Enforced: `path` `symbol`. Test: `test path` "<test name>", or none.

## Invariants
<Facts about stored data that must hold after every write, on every path. One per bullet.>
- <DOM>-INV-001: <the fact, in one sentence>
  Enforced: `path` `symbol`. Test: `test path` "<test name>", or none.

## Cross-module impacts
<What a change in this domain does to another module, repo or app.>
- <DOM>-CS-001: <when X changes here, Y there must ...>
  Affects: `repo/path`. Test: `test path` "<test name>", or none.

## Gotchas
<What misleads or breaks a change in this domain, and why. One per bullet.>
- <DOM>-GT-001: <the trap, in one sentence> (`path` `symbol`, learned <YYYY-MM-DD>)
