---
source_commit: {<repo>: <sha>}
---
# <Domain>

<What this domain does for the business, in two or three sentences, and the repos and folders
that hold it.>

## Terms
| Term | Meaning | Name in code |
|---|---|---|

## Key flows
<Only flows that cross modules or repos.>
### <Flow name>
1. <step> (`path` `symbol`)

## Interfaces
<The files that define this domain's routes, events and schemas. List an entry only when its
name doesn't say what it does.>

## Data
| Entity or table | Written by | Defined in |
|---|---|---|

## Rules
<Only rules the code can't show on its own, that a future change must keep, and that something
enforces. One rule per bullet. IDs never change, and a removed rule's ID is not reused.>
- <DOM>-R1: <the rule, in one sentence>
  Enforced: `path` `symbol`. Test: `test path` "<test name>", or none.

## Gotchas
- <what misleads or breaks, and why> (`path` `symbol`, learned <YYYY-MM-DD>)

## Where to change things
| To change... | Look at | Also update |
|---|---|---|
