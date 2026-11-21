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
