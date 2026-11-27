# <Imperative title, under 70 characters>

## Goal
<One or two sentences on what changes for the user and why.>

## Scope
- In: <what this change does>
- Out: <what someone could reasonably expect it to do, which it deliberately won't>

## Acceptance criteria
- [ ] AC1: Given <state>, when <action>, then <observable result, with real values>

## Decisions
| Decision | Choice | Rejected | Why, and the cost we accept | Decided by |
|---|---|---|---|---|
| <open point> | <choice> | <other options> | <reason; downside> | person / planner |

## Contracts (required when tasks in different repos or areas talk to each other)
<Each endpoint or event once: method and path or topic, request, response, errors. Tasks cite
these by name.>

## Design

### Components
<Components touched or added, and what each one does in this change.>

### Data flow
<How a request moves through the components, step by step. Add a mermaid diagram only when it
helps.>

### Data changes
<New or changed tables, columns, indexes and stored fields, with the expected volume. "None" when
nothing stored changes.>

### Failure handling
<Each way it can fail and what happens: bad input, a dependency down, two users at once.>

### Access
<Who may call each new entry point, and what a caller who may not gets.>

## Tasks
| ID | Repo / area | Change | Criteria | Files | Depends on | Verify |
|---|---|---|---|---|---|---|
| T1 | <repo> / <fe, be, db, ...> | <what to change, naming functions and endpoints> | AC1 | <paths> | — | `<command>` → <expected result> |

## Test plan
| ID | Criteria | Level | Repo / file | Given / when | Then |
|---|---|---|---|---|---|
| TP1 | AC1 | <unit / integration / e2e> | <repo> / <test file> | <entry point and test data> | <exact expected result> |

## Rollout and rollback
<Deploy order, migration steps (expand, migrate, contract), how to turn it off, and what can't
be undone. When none of these apply: "Revert the PR.">

## Risks and assumptions
- <risk, unknown or assumption> → <the first task that probes it, a fallback, or accepted>

## Open questions
- <question> Recommended: <answer>. Approving the plan accepts it. Otherwise "None".
