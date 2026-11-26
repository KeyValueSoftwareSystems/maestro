# Test report: <change>

Commit: <repo: sha, per repo> · Verdict: <pass | fail>
Totals: <run> run, <passed> passed, <failed> failed, <flaky> flaky, <skipped> skipped
Environment: <runtime and service versions, how services were started, random seed>
Doubles: <third-party services replaced in integration or e2e tests, or "None">

## Results
| Test-plan row | Test (file::name) | Result | Notes |
|---|---|---|---|
| <row ID> | <path::test> | <pass / fail / flaky (k of n failed) / not run> | <why, if not pass> |

## Failures
| Test | Class (product / test / environment) | Cause | Evidence (log or file:line) | Rerun command | Status | Note |
|---|---|---|---|---|---|---|
<Status starts as `open`. Whoever fixes a row sets it to `fixed`, or `disputed` with the reason.>

## Tests changed
| Test | Change | Why (requirement or plan row) |
|---|---|---|
<Otherwise "None".>

## Commands run
- `<command>` → exit <code>: <passed>/<total>, <skipped> skipped

## Not covered
- <Anything the plan asked for that could not be tested, and each skipped test, with the reason.
  Otherwise "None".>
