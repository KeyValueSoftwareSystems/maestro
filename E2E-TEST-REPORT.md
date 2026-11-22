# Maestro v2: end-to-end test report

Date: 2026-11-21 · Branch: `v2` at `627edbf`, plus 2 uncommitted fixes · Not committed

## Summary
Every workflow ran end to end in real Claude Code: init, knowledge, bug-fix, minor feature, major
feature, sync and the archive subworkflow. Each run started from a slash command and ended with a
pushed branch, an opened PR, removed worktrees and `status: done`. Resume, a rejected gate,
`on_fail` retry, the "same failure twice" stop and recovery after an interruption all worked.

- **19 scenarios: all passed.** Three hit a problem along the way:
  - init's `wire` step needed a manual copy (D1);
  - a docs conflict showed up at merge time (D2);
  - one PR check tripped on my fake `gh`, which I fixed in the test setup.
- **3 wording bugs found and fixed**, two of them verified in later runs (see Fixed).
- **5 issues need your decision** (see Decisions). None blocks a run.
- **Cost:** $34.40 across 15 sessions.

## How it was tested
- **Runs:** real headless Claude Code (`claude -p` 2.1.319), one session per run, resumed with
  `--resume` to answer gates as the person. Lead and agents ran on Opus 5.5; worker steps on Haiku 5.5.
- **Permissions:** no bypass. Each session got an allowlist: file tools, Agent and Skill, and
  `git`, `npm`, `node`, `gh` and basic shell commands. Edits were auto-accepted.
- **Workspaces**, in the scratchpad `e2e/` folder, each with local bare repos as `origin`:
  - **w1:** a single Node repo, `invoice-svc`, with a planted discount bug.
  - **w2:** an umbrella with `codebase/api` and `codebase/web`.
  - **w3:** an empty repo for the loop tests.
- **GitHub:** a fake `gh` that logs calls, remembers PRs and prints fake URLs. Nothing reached GitHub.
- **Checking:** I checked every result in the repos myself (branches, worktrees, origin, state.yaml,
  logs), not only the agents' replies.

## Scenarios
| # | Scenario | Result | Evidence |
|---|---|---|---|
| 1 | `install.sh` into a single repo and an umbrella | Pass | 9 skills, 6 commands, workflows and stacks in place |
| 2 | `/maestro-init`, single repo | Pass* | Found the repo, `node` stack and `setup/build/lint/test`; clear gate summary. *`wire` blocked (D1) |
| 3 | `/maestro-init` umbrella, then the knowledge base | Pass | Found `api` and `web`, skipped the code-less root. KB review failed round 1 on a real bug (`GET //` crash), rebuilt and passed round 2 |
| 4 | `/maestro-kb`, single repo | Pass | `architecture.md` and a domain doc; `source_commit` = HEAD; flagged the planted bug as a gotcha |
| 5 | Optional gate declined ("No, not now") | Pass | Ended `stopped` with a clear summary |
| 6 | `/maestro-fix`, single repo | Pass | Sherlock proved the cause by toggling the line and left the failing test in the run's worktree. Steps: worktree reused → test-first fix → checks 4/4 → review → docs on the branch → PR → cleanup. 10 steps |
| 7 | Resume from a new session at a gate (`/maestro-fix <slug>`) | Pass | Read `state.yaml`, showed the same gate, continued |
| 8 | `/maestro-minor` with the ship gate rejected ("add the R1 test first") | Pass | Went back to build, added the test, re-ran checks, test, review and docs, then the gate. 17 steps |
| 9 | `/maestro-minor` that clashes with a repo rule (asks for `console.log`, which lint bans) | Pass | Planner stopped to ask, with 3 options and a recommendation; built a logger hook; lint untouched |
| 10 | `/maestro-feature` across `api` + `web` | Pass | Plan review → worktree per repo → build and write-tests in parallel (no clashes) → commit → checks → review → verify 21/21 → docs → 2 PRs (`api: …`, `web: …`) → cleanup. Flagged that api must deploy before web. 13 steps |
| 11 | `/maestro-sync`, single repo after a squash merge | Pass | Fast-forwarded `main`, moved `source_commit`, replaced a branch-only commit ID in the docs |
| 12 | `/maestro-sync`, umbrella after both PRs merged | Pass | Fast-forwarded both repos; docs pointed at the merge commits |
| 13 | Upgrade with `install.sh --force-workflows` | Pass | Only the changed workflow file differed |
| 14 | `on_fail` retry (test workflow) | Pass | check failed → `make` → check passed |
| 15 | Same failure twice | Pass | Stopped after 2 identical failures and asked: retry, jump or stop |
| 16 | Interrupted mid-step (usage limit), resumed from a new session | Pass | Saw `rca.md` was complete though `state.yaml` wasn't updated; counted the step done instead of re-running it |
| 17 | PR step re-run when the PR already exists | Pass | Reused the open PR; no duplicate |
| 18 | `/maestro-fix` in the umbrella (api crash) | Pass | Sherlock's worktree landed at the workspace-root path the worktree step reuses; found 10 crashing paths, not just `//`. Fix verified against a running server. 10 steps |
| 19 | Person's checkout never touched; two runs at once in one repo | Pass* | Every run branched from `origin/main` in its own worktree. *Both runs edited the docs, which conflicts at merge (D2) |

## Fixed during testing (uncommitted)
1. **PR titles copied the RCA heading**, e.g. "Root cause: a 10% discount…".
   - Fix: in `archive.yaml`, "Title it with what the change does".
   - Verified: "Add an optional log hook…" and "Stop request targets starting with // from
     crashing the api".
2. **PR bodies and docs linked to `.maestro/runs/…`**, which isn't in any repo.
   - Fix: one line in the lead's agent prompt: "`<run folder>` is in no repo: never link or cite its
     files in code, docs, commits or PRs."
   - Verified: the crash-fix PR body and its new doc lines have no run links.
   - Older doc lines from before the fix still have them (D5).
3. **Gates counted differently in `steps_used`.** One init run counted the gate and the other didn't.
   - Fix: the lead now says "a gate doesn't count".
   - Not re-tested.

`check.sh` passes. Diff: `skills/maestro/SKILL.md` (+2 lines) and `workflows/subworkflows/archive.yaml`
(+1 line).

## Decisions for you
| # | Issue | What happened | Options |
|---|---|---|---|
| D1 | **Resolved:** `install.sh` now installs only the stacks `workspace.yaml` lists, and init's `wire` step is gone. Originally: init's `wire` step writes into `.claude/skills/` | Claude Code protects `.claude/`, so the copy was blocked in both workspaces. The lead stopped cleanly and offered 3 options; I copied it by hand. Interactively you'd likely get a permission prompt (not verified) | (a) `install.sh` installs all 4 stacks into `.claude/skills/` and `wire` is removed (simplest, and no runtime writes to `.claude/`); (b) keep it and accept a prompt per init; (c) make `wire` inline so the prompt appears in your conversation |
| D2 | Two runs at once in one repo conflict on docs | The fix and the minor run both updated `docs/` on their branches (the `learn` step), so the second merge conflicted in both docs | (a) Accept it and rebase the second PR (simple, docs ship with the code); (b) drop `learn` from archive and let `/maestro-sync` refresh docs after merge (no conflicts, but docs lag); (c) `learn` writes only notes, and sync applies them |
| D3 | Cost per run | bug-fix ≈ $3–4, minor ≈ $4–6 (one rework round included), 2-repo feature ≈ $7, init+KB ≈ $1.5–3.7 | Run the lead on Sonnet; keep Opus for plan, code review and debug; Haiku already does git and PR steps |
| D4 | Doc edits left uncommitted | Sync's refresh on `main`, and `learn` in an umbrella, leave edits uncommitted by design. Easy to forget, so docs drift | (a) Keep and say so at `done`, as the lead did; (b) sync and `learn` commit docs on a `docs/<slug>` branch and open a PR |
| D5 | Small items | `install.sh` prints "Next: /maestro-init" on upgrade too, and leaves `.gitignore` modified for you to commit; older docs still cite run files | One-line fixes if you want them |

## Confirmation test after commit `42d7f4e`
| Check | Result |
|---|---|
| Fresh repo: `install.sh` → `/maestro-init` → `install.sh` again | Pass. No `.maestro/stacks/` and no writes to `.claude/`. The gate told me to re-run install, and the second run installed only `node` |
| Gates don't count toward `steps_used` | Pass. `steps_used: 1` after detect plus two gates |
| Umbrella bug fix (web crash on a missing total) | Pass. Fix ran on Sonnet. Docs ran on Opus and were committed on `docs/invoice-missing-total` in a worktree. Two PRs (fix, and docs linking the fix); both worktrees removed; umbrella checkout clean; `done` in 9 steps |
| Seen once, not fixed | The PR worker ran `gh pr create` from the workspace root with a made-up `--repo-dir` flag. Real `gh` would reject that, so the step would fail visibly. It also left its PR-body file at the root, and the lead cleaned it up. Watch for it before adding a line |

## What the agents did well, unprompted
- Socrates found both planted bugs while writing docs, and recorded them as gotchas.
- Keystone and grill-me asked only when the request clashed with a repo rule. Otherwise they recorded
  their own calls in Decisions.
- Keystone noticed an unmerged branch that would conflict with its plan.
- Sherlock proved each cause by turning it off and on, found every path with the same cause, and
  flagged data already stored with wrong totals.
- The lead recovered an interrupted step from the files on disk, and disclosed workarounds honestly.

## Not tested
- Python, Java and React stacks.
- A real e2e environment (docker compose).
- Builds over 10 minutes; flaky tests; Litmus's environment-failure path.
- A plan-review or code-review `on_fail` loop (both passed first time).
- Re-running init to add a repo; template overrides from `.maestro/templates/`.
- Interactive mode: everything here was headless, so the interview and `.claude/` prompts may differ.

## Where things are
Scratch, under this session's scratchpad `e2e/` folder:
- `w1/`, `w2/`, `w3/` (with `.maestro/runs/` for every run), and `origins/` holding the pushed branches;
- `logs/` (session JSON, `gh.log`, `gh-prs.txt`);
- `run.sh`.

## Round 2: the new major-feature flow (2026-11-22)
Flow under test: intake → questions → plan (with the e2e test plan) → approve → worktree →
build ‖ write-tests → commit → checks → code-review ⇄ fix-review → verify ⇄ fix-tests → archive.
Same harness as above (`claude -p` 2.1.319, allowlist, fake `gh`, local bare origins).

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 20 | `next` loops, deterministic (exec steps that fail until a Haiku worker fixes them) | Pass | 8 steps: review → fix-review → review → verify → fix-tests → verify → finish; fix steps skipped in normal order; `done` |
| 21 | Full `/maestro-feature` from a Jira-style ticket | Pass | intake kept the ticket word for word under Source and listed 8 open questions; 5 questions asked one at a time into `answers.md`; Keystone asked none of them again and raised one real trade-off; PR opened, worktree removed, `done` in 18 steps ($4.68 for the main session) |
| 22 | Code-review loop with real agents (a test hook planted a fake live key in the first commit) | Pass | Birbal blocked it → Brew removed it → Birbal blocked again because the key was still in branch history → the lead stopped and asked rather than loop → reset → passed in round 3 |
| 23 | Verify loop with real agents (a discount bug only the e2e test catches) | Pass | Litmus failed TP1 as a product bug → Brew fixed and committed → Litmus passed; `done` in 4 steps |
| 24 | Resume from a new session with `/maestro-feature <slug>` after a failed parallel step | Pass | Retried build and write-tests and carried on |

Fixed during round 2:
1. **Subagents could not run `cd <worktree> && git …`.** Claude Code asks for approval for that pattern, which a headless or parallel subagent can't get, so build and write-tests both failed and stopped using Bash. `git -C <worktree> …` and `cd <worktree> && npm …` are allowed. Fix: one line in the lead's agent prompt.
2. **The questions step suggested answers** to every question, which skips the person's own thinking. Fix: one line in `questions.md`. Re-tested: no suggestions.
3. **check.sh's new step-target check matched nothing on macOS** (BSD `sed` has no `\|`). Fixed with `sed -E`, and checked that a misspelled `next` now fails.

## Round 3: archive the plan as `docs/plans/<slug>.md` (2026-11-22)
Same harness. w9 is a single repo seeded with three old "euro" plans under `docs/plans/`; w10 is a
multi-repo workspace (api, web, umbrella). Both ran `/maestro-minor` to `done`.

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 25 | Plan saved with the change, single repo | Pass | `docs/plans/invoice-format-amount.md` committed on `feat/invoice-format-amount` and in the code PR; `done` in 11 steps |
| 26 | Plan saved with the change, multi-repo | Pass | `docs/plans/health-endpoint.md` committed on the umbrella's `docs/health-endpoint`; api PR and docs PR opened; worktrees removed; `done` in 12 steps |
| 27 | Slug check sees `docs/plans/` | Pass | `format-amount`, `amount-formatter` and `currency-formatter` were taken, so the lead chose `invoice-format-amount` |
| 28 | Old plans stay out of the way | Pass | Keystone never opened them and planned USD, not the old plans' euros. Socrates peeked at one with `head` and left it unchanged. Claude Code's Grep and the CLI `rg` both skip `docs/plans/` through `.ignore`; Glob and `ls` still list it |

Fixed during round 3:
1. **The PR agent ran `gh pr create` from the workspace root** in the multi-repo run, so it aimed at the
   wrong repo. Cause: the lead's "run git as `git -C`" line made the agent avoid `cd` for every
   command. Fix: one more lead line, "Run other commands there, such as gh or npm, as
   `cd <path> && <command>`." Re-tested: both PRs were created from their worktrees.
2. Harness only: the fake `gh` now honours `-R`, and the api seed's broken build and lint scripts
   were fixed on the run's branch.

## Round 4: the quiz (T7, 2026-11-22)
`quiz-write` (Sonnet worker) writes 5 questions with answers to `quiz.md`; `quiz` (inline worker)
offers it, asks one at a time, and never fails the run. Tested by resuming a w9 run at `quiz-write`.

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 29 | Quiz written from the plan and the diff | Pass | 2 feature questions and 3 "where in the code" questions; every file, function and line in the answers matched the code ($0.48 for the step) |
| 30 | Taking the quiz | Pass | Offered with a skip option; one question at a time; a half-right answer got what was right plus the correction, shown only after the reply |
| 31 | Skipping midway | Pass | "Skip the rest" passed the step (history: "took 2 of 5 then skipped") and the run went on to archive |

## Round 5: rule IDs with tests in domain docs (A8, 2026-11-22)
The domain template's Rules section now keeps only rules the code can't show, that a future change
must keep and that something enforces, one per bullet: `<DOM>-R<n>`, where it is enforced, and its
test. Tested with `/maestro-kb` on w11, a docs-free copy of w2 ($2.08, review passed).

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 32 | Rules written in the new shape | Pass | 9 rules, INV-R1 to INV-R9, each with Enforced and Test; partial coverage noted ("POST only"). The old doc packed the same facts into 5 multi-rule bullets with no tests |
| 33 | Filter drops code restatements | Pass | "web renders id, customer and total only" is gone |
| 34 | Test links are checkable | Pass | All 6 sampled test names exist verbatim; Birbal checked every one, and flagged INV-R8, whose test covers `searchInvoices` but not `fetchInvoices` |

Not as hoped: the domain doc grew from 76 to 88 lines, because each rule now takes two lines.

## Round 6: the person's hypothesis in bug-fix (T4, 2026-11-22)
`hypothesis` (inline worker) asks for a one-sentence guess, without suggesting causes, and saves it
word for word; `investigate` tests it first without assuming it. Tested on w9's real divide-by-10
discount bug with a deliberately wrong guess, stopped at the confirm gate ($1.19).

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 35 | Asking for the guess | Pass | One question, "No idea" offered, no causes suggested; `hypothesis.md` holds the answer word for word |
| 36 | A wrong guess doesn't anchor Sherlock | Pass | rca.md lists the guess as hypothesis 1, **ruled out** with evidence (subtotal is exactly 100; `lineTotal` has no rounding), and confirms the real cause (`applyDiscount` divides by 10) by toggling the one-character fix |

## Round 7: Litmus commits the test bugs it fixes (N1, 2026-11-22)
Litmus already fixes failures it classifies as test bugs in run mode, but nothing told it to
commit, so the fix would miss the PR and block cleanup. `verify` (major) and `test` (minor) now say
"Commit any test you fix on ${branch}." Tested by resuming a w9 run at `verify` with a planted test
bug: the TP2 test fed `0.124` but expected the plan's `0.125 → $0.13`.

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 37 | Test bug fixed and committed in verify | Pass | Classified as a test bug; input changed back to `0.125`, expected value untouched; committed as `bd3e44a`; worktree clean; verify passed and the run went on to the quiz ($0.82) |

## Round 8: duplicate workflow lines removed (2026-11-22)
A review found workflow lines that only repeat an agent skill's default. Round 7's premise was
wrong: Litmus's default already says "Commit: Yes for every test you write or fix". Removed: the
commit lines in `verify`, `test`, `fix-review` and `fix-tests`; "Do not fix the bug" in
`investigate`; the repo/area and parallel-files line in major `plan`; "Never paste secrets or raw
logs" in `pr`; and "Every claim must match the code it cites" in knowledge `review`.

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 38 | Round 7 re-run without the commit line | Pass | Classified as a test bug; input put back to `0.125`; committed as `38ebed3`; worktree clean; verify passed and the run went on to the quiz ($0.87) |
