# Review: <what was reviewed>

Against: <path> · Round: <n> · Reviewed: <base sha>..<head sha> · Verdict: <pass | fail>
Scope: <full | partial (what was not read line by line)> · Fresh context: <yes | no> · Ran: <commands and results, or none>
<!-- REVIEW: birbal J5: Fresh context field records whether the reviewer wrote the work. -->

## Requirements
<For code reviewed against a plan, request or root-cause report. Each "no" is also a blocker row.>
| Requirement or task | Met | Evidence (file:line or test) |
|---|---|---|

## Findings
| ID | Severity | Where (file:line) | Finding | Status | Note |
|---|---|---|---|---|---|
| R1 | <blocker / major / minor / nit> | <path:line> | <what is wrong, why it matters, and the fix if not obvious> | open | |

Status: `open`, then `fixed` or `disputed` by the author, then `closed`, `withdrawn`, `upheld` or
`escalated` by the reviewer.
<!-- REVIEW: birbal R4: the verdict and status rules repeated SKILL.md's; kept only the Status values. -->

## Outside this change
- <Problems in code the change didn't touch, as follow-ups. They never affect the verdict.
  Otherwise "None".>

## Summary
<Two or three sentences: the overall state, what you checked, and what must change before this
ships. List any escalated rows here for a person to decide.>
