# v2 SDLC review: open list

Date: 2026-11-21 · Branch `v2` · A-list fixes committed in `50368e3` · This file is not committed.

**Sources:** two independent reviews of the whole repo.
- **Process:** against NIST SSDF, Google eng-practices, DORA and OWASP SAMM.
- **Consistency:** skills against workflows, templates and docs.

Every finding was checked against the files.

**Rule for adding lines:** only conventions the agent can't infer, fixes to our own wording, or habits seen failing. Test "be careful" guards first.

**Committed:** A1, A4–A8, A12 and A15, plus `pr`/`docs-pr` on Sonnet, in `50368e3`.

## A. Wording fixes, each adding at most a line
| # | Status | Problem | Fix |
|---|---|---|---|
| A1 | **Done** (`50368e3`) | Litmus left tests it fixes in run mode (`verify`, minor `test`) uncommitted, so the PR missed them and `cleanup` failed | `litmus` Commit row: "Yes for every test you write or fix, unless you are told not to." |
| A2 | **Dropped** (tested) | Birbal and Socrates diff against the local `main`, which may be stale | Opus Birbal picked `origin/main` itself and reviewed only the feature |
| A3 | **Dropped** (tested) | Brew's "Every hunk must trace to a task. Remove stray edits" could delete Litmus's tests during parallel build ‖ write-tests (`brew:45`) | 3 of 3 Sonnet Brew runs, given the real `build` prompt, kept Litmus's new test and edited fixture, and named them as the tester's |
| A4 | **Done** (`50368e3`; single-repo `docs-pr` pass verified in 2 runs) | The lead fails "a pass when a file the task names doesn't exist" (`maestro:130`). `docs-pr` says "if the worktree exists… otherwise pass", and the single-repo path is untested | "a file the task says to **write**" |
| A5 | **Done** (`50368e3`) | Litmus says "every **required** row passed" (`litmus:69`), but nothing marks rows required. It also fails "when a test-plan row has no test" (`litmus:50`), but `write-tests` owns only the integration and e2e rows | Drop "required"; say "a row you were asked to cover" |
| A6 | **Done** (`50368e3`) | Birbal re-reviews only `fixed`/`disputed` rows plus "the diff since the commit the last round reviewed" (`birbal:72`). Plans and docs aren't committed, and Socrates never marks rows. "missed in round n" isn't a status (`birbal:81`) | "Review the `open`, `fixed` and `disputed` rows, plus what changed since the last round"; a missed blocker becomes `open` with the note "missed in round n" |
| A7 | **Done** (`50368e3`; without the `!` part, per user) | major-feature `commit` hard-codes `feat(${slug}): …` (`major-feature:65`), ignoring the repo convention and `!`/BREAKING CHANGE | "…in the repo's commit message convention (otherwise Conventional Commits, `!` for breaking)" |
| A8 | **Done** (`50368e3`) | sync doesn't fetch the umbrella root, but docs PRs merge there (`sync:11`) | "…and the workspace root, if it is a git repo" |
| A9 | **Dropped** (the workspace root is always a git repo, per user) | `learn` assumes the umbrella root is a git repo (`archive:13-16`) | "If the workspace root isn't a git repo, edit docs/ in place." |
| A10 | **Dropped** (checked plans: Keystone records who may call without a template slot) | Keystone must pin "who may call each new entry point", but the plan template has no place for it outside Design (`plan.md:19`) | Contracts placeholder: "…request, response, errors, and who may call it." |
| A11 | **Dropped** (the lead recorded `docs_pr` and listed it unprompted) | `docs-pr` records no URL, so the final summary leaves out the docs PR | "Record its URL as `docs_pr`." |
| A12 | **Done** (`50368e3`) | The lead's state.yaml example has a relative `worktree` path (`maestro:42`), but steps record absolute paths | Make the example absolute |
| A13 | **Open** (user will rework the Litmus/Brew split at the end: Litmus only writes and runs tests, Brew fixes) | major-feature `write-tests` "Touch only test files." contradicts Litmus, which allows fixtures | Delete that sentence |
| A14 | **Dropped** (Opus Birbal checked plan security unprompted in scenario 10) | The plan review doesn't check the threats and controls the design names (SSDF PW.2.1) (`birbal:54`, check 7) | Add: "each new entry point, store or external call names its threats and controls, and each control has a test-plan row" |
| A15 | **Done** (`50368e3`; only the PR template and title convention, items 1–3 dropped since agents already do them) | The PR is the only record that outlives the run, but its body leaves out the ticket, rollout/rollback and follow-ups, and bypasses the repo's PR template (Google CL descriptions; `gh --body` skips the template) (`archive:29-31`) | PR body: "Cite any ticket ID in request.md. Copy the plan's Rollout and rollback (or the RCA's data repair). Under Follow-ups, list escalated review rows, Outside this change, the RCA's Prevention items and anything not verified. Fill in the repo's PR template and follow its title convention, if it has them." |

**Stale docs: done (uncommitted).** The workflow-size aim moved from 80 to 100 lines.
- **README:**
  - Quick start: say to run `install.sh` again after `/maestro-init`;
  - line 31, "wires the stack skills": should say "offers to build the knowledge base";
  - lines 34-35: mention the docs PR in umbrellas;
  - lines 79-83: say umbrella docs live at the root and ship as a docs PR; state that the workspace root must be a git repo;
  - lines 86-88: `install.sh`, not init, installs the listed stacks.
- **AGENTS.md:**
  - line 18, "Copies everything above": it copies only the listed stacks;
  - line 41: the workflow-size aim of 80 lines (major-feature is 91);
  - lines 70-71: list the checks `check.sh` runs.

## B. Decisions for the user
| # | Proposal | Why | Cost |
|---|---|---|---|
| B1 | **Ignored** (per user). An `audit` command in `checks`: dependency, secret and SAST scans, taken from the repo's CI or pre-commit config | Scans are only in skill text today, and nothing scans for secrets before the push (DORA pervasive security, OWASP SAMM Secure Build, GitHub leaked-secret guidance) | One clause in init detect; `[build, lint, test, audit]` in 3 checks steps; repos without one skip it |
| B2 | **Kept as is for now** (per user: kb and sync leave docs uncommitted). Docs branch and PR for `/maestro-kb` and `/maestro-sync` too (the rest of D4) | Their edits sit uncommitted. In a single repo, sync's own leftover edits make the tree dirty, so the next sync skips that repo | Similar wording in 2 workflows plus a docs-PR step; a shared subworkflow needs discussion |
| B3 | **Dropped** (per user: runs must not be gitignored). Ignore `.maestro/runs/` in `.gitignore` | In a single repo, run files sit in the person's checkout and `git add -A` commits them; the PR is the record | One line in `install.sh` |
| B4 | **Dropped** (Keystone already splits by scope, and the person approves the plan). PR size budget: Keystone proposes a split above about 400 changed lines per repo | Google small CLs, DORA small batches | One clause in the major-feature plan step |
| B5 | **Done** (uncommitted: Opus on the knowledge build, its review and sync refresh). Pin the knowledge build (and sync refresh) to `model: opus` | Same reason as `learn`: later runs depend on the docs | One line each |

## Ideas tested
**Continue a step's subagent on a re-run, instead of starting a new one** (2026-11-21). Not adopted.
- **Test:** the same looping `/maestro-minor` ran twice on Opus, with build/test on Sonnet: plan, build,
  test, review and docs, then a rejected ship gate asking for new work, round 2, then ship. One run used
  fresh agents; the other had a 5-line lead rule to continue the same agent with SendMessage.
- **It works:** the lead kept agent IDs in state.yaml and continued build, test, review and docs, also
  across `--resume` turns. A new session can't continue them ("No transcript found").
- **No saving:** round 2 needed fewer tool calls (build 20→10, test 20→13, review 18→15, docs 34→34),
  but token cost was the same or higher (−7%, +1%, +13%, +5%). After the gap, the continued agent
  re-caches its whole history. Run totals: $5.95 fresh against $6.81 continued (2 extra steps came
  from test allowlist denials).
- **Revisit** only for quick on_fail retries (checks → build), where the cache may still be warm. Not measured.

## Later (user's plan)
- **Archive the plan as history.** Done 2026-11-22: learn saves the plan (or RCA) as `docs/plans/<slug>.md`
  with the change; `install.sh` writes a `.ignore` for `docs/plans/`. The run folder stays local.
- **Litmus/Brew split (A13).** Litmus only writes and runs tests, and Brew does all the fixing.

## C. Skipped, with reasons
- **Already handled by the agents in testing:** "commit all changes" excluded junk; bug-fix reviews passed with RCA prevention items.
- **Speculative or rare:**
  - Brew fixing lint in Litmus's test files;
  - running `checks` after `test` in minor;
  - stack skills not yet installed during init's knowledge review;
  - init's `repos` record;
  - `/maestro-kb`'s focus argument;
  - Birbal's "docs updated" check.
- **Seen, but nothing went wrong (watch):** in the A3 test, 2 of 3 Brew runs used `git stash` to check whether a failing `npm test` was already broken. In the parallel step, that briefly removes Litmus's uncommitted fixture edits. `stash pop` restored them every time.
- **Out of scope** (team CI/CD and branch protection): two-person approval, versioning and changelogs, SBOM and signing, deploys.

## Next
Go through A3 onward one by one (explain, then apply), then the stale docs, then B1–B5 decisions. Commit when the user asks.
