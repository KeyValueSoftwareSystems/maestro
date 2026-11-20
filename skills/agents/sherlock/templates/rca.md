# Root cause: <bug title>

Confidence: <confirmed | unconfirmed> · Introduced in: <commit or PR, or unknown>

## Symptom
<What the person sees: expected vs actual.>

## Reproduction
Version: <repo: sha> · Environment: <runtime, config, data>
Steps or command: <exact>
Rate: <e.g. 20 of 20 runs> · Minimal case: <the smallest input or steps that still fail>

## Root cause
<The wrong decision in the code, with file:line, and how it produces the symptom.>

Contributing factors: <what let it through, or "None">

## Hypotheses
| # | Hypothesis | Experiment and prediction | Result (confirmed / ruled out, with evidence) |
|---|---|---|---|

## Same cause elsewhere
- <file:line>, or "None. Searched for: <pattern>"

## Failing test
File: <path> · Run: `<command>` · Fails with: <quoted assertion message>
```
<a test that fails now and will pass after the fix>
```

## Impact
<Who and which versions are affected, since when, and any bad data or state that needs repair.>

## Fix
- Fix: <the change at the root cause, covering every instance above>
- Mitigation: <only if needed now; otherwise "None">
- Prevention: <one item per test, type, check or alert that should have caught it>

## Repos and areas affected
- <repo / area>

## Open questions
- <otherwise "None">
