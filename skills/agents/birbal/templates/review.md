# Review: <what was reviewed>

Against: <path> · Round: <n> · Reviewed: <base sha>..<head sha> · Verdict: <pass | fail>
Scope: <full | partial (what was not read line by line)> · Ran: <commands and results, or none>

## Requirements
<For code reviewed against a plan, request or root-cause report. Each "no" is also a blocker row.>
| Requirement or task | Met | Evidence (file:line or test) |
|---|---|---|

## Findings
| ID | Severity | Where (file:line) | Finding | Status | Note |
|---|---|---|---|---|---|
| R1 | <blocker / major / minor / nit> | <path:line> | <what is wrong, why it matters, and the fix if not obvious> | open | |

The author sets Status to `fixed` or `disputed`. The reviewer then sets it to `closed`,
`withdrawn`, `upheld` or `escalated`. A blocker or major row that is `open` or `upheld` fails
the review. A minor that starts with `question:` asks the author to confirm or explain, and never
fails the review.

## Outside this change
- <Problems in code the change didn't touch, as follow-ups. They never affect the verdict.
  Otherwise "None".>

## Summary
<Two or three sentences: the overall state, what you checked, and what must change before this
ships. List any escalated rows here for a person to decide.>
