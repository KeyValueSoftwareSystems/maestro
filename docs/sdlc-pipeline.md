# The included SDLC pipeline

Maestro ships one complete example workflow, `.maestro/workflows/sdlc-main.yaml`. This page
explains what it does at each stage. To run it, see the [README](../README.md#start-your-first-feature).

## The stages

Shipped as a worked example (`.maestro/workflows/sdlc-main.yaml` + the installed skills
pack) — a full AI-SDLC pipeline you can run today and fork into your own:

```
workspace sync → requirement → PRD (summarize context → Grill unclear decisions → write once → validate
                                    → [approve]; a minor change with nothing to ask skips the approval)
   → plan: brainstorm with you (a conversation you lead and end) → [write the plan?]
       → write docs/plans/active/<slug>.md → validate → commit
       → [greenfield: create and scaffold the new repositories] → [approve the plan]
     ‖ functional test cases, at the same time, from the PRD alone (every AC traced; no gate)
   → plan still current? → implement every repo (parallel; 2+ slice groups → one agent per slice,
     engine-verified build/lint/test, reviewed)
   → QA (product bug → fix that repo, re-verify, re-review → QA again)
   → acceptance-criteria trace → design-vs-code drift check → decision log → review pack
   → [approve release] → [confirm archive] → branches or pull requests (per config)
          → compare the plan with what was built → [keep or update the plan]
          → move it to docs/plans/completed/ → harvest lessons, refresh docs/ → remove worktrees
```

A bug takes its own, shorter flow; see [Fixing a bug](#fixing-a-bug).

**Roles.** Each step is done by a role, and the workflow fixes the order in which work passes
between them; no model chooses who goes next.

| Role | Jobs in the shipped pipeline |
|---|---|
| `product` | intake context; prepare the feature goal and product questions; write and revise the PRD; pin a bug down with you |
| `architect` | the brainstorm, the plan and its revisions; comparing the plan with what was built at archive |
| `reviewer` | code review, design drift |
| `implementer` (developer) | the task plan, the code, fixes from verification and review; scaffolds new repositories |
| `qa` | the functional test cases; reproducing a bug; the automated QA run and test-harness fixes |
| `analyst` | knowledge refresh, the review pack, a bug's fix proposal, the retrospective |

You answer the interviews and decide every approval in between. The engine checks each job's
output when it hands off (`check:`) and sends a failed check back to the same job with its report.
The step's role is named at the top of its prompt, so it holds on every host, also for the jobs the
lead runs in its own session to keep the interview context.

**You define the workflow; you bring the skills.** The engine is the product. A workflow is a YAML file describing what runs in what order; each agent step names a *skill* (a reusable prompt) — yours, ours, or a third party's (Obra, Superpowers, …). The workflow owns *where* artifacts land and *when* each step runs; the skill owns only *how* to do its one job, so any skill can be swapped without touching the graph.

## Running a feature in detail

Called without an explicit slug, the lead agent asks the engine which runs exist. If you
already supplied a feature description and there are no runs to resume, it derives and shows a
kebab-case slug and starts immediately; it does not ask you to repeat the description in a
different format. When a choice is required, Claude Code uses `AskUserQuestion` and Codex uses
`request_user_input` when its current mode exposes that tool. Hosts or modes without a native
selector fall back to a numbered text prompt.

**Seeing what's happening.** The run keeps your agent's own task list in step with the engine:
each stage of the flow is a todo (done, in progress, waiting on you, still to come), the running
stage expands into its parts, and the open step is named — e.g.
`Design phase › Plan — waiting on you: Plan approval`. The same checklist is one command away in any
terminal:

```
$ python3 .maestro/engine/maestroctl.py todo --slug my-feature
my-feature · sdlc-main · running
[x] Workspace sync (feature start)
[>] Design phase
    [x] Requirement and context
    [x] PRD
    [>] Plan and test cases
        [?] Plan
              ↳ waiting on you: [plan] Plan approval
        [x] Functional test cases
[ ] Implementation, QA and release
[ ] Pull requests and archival
```

On first run the lead agent scaffolds `.maestro/runs/my-feature/requirement/`. Drop any requirement files in there (PRDs, tickets, notes, reference links — every file is read); the shipped pipeline then **builds a PRD** (`requirement/prd.md`) before the plan:

- **valid existing `prd.md`** → it goes directly to PRD approval; common equivalent headings
  are accepted because PRDs have no universal format;
- **the client's own PRD in another shape** (a document of 250+ words, or any PDF/Word/ODT/RTF
  file) → a worker agent rewrites it into the PRD structure, keeping the client's facts and
  wording and adding nothing; the product role then lists only the material facts it leaves open.
  Only those are asked (in `auto` mode, adopted as assumptions), then the writer fills them in. A client file
  named `prd.md` is kept as `prd.original.md` first; source files are never edited. A PRD still
  marked "(to confirm)" fails validation;
- **a short request or nothing** → it summarizes the project context and feature goal without stopping,
  then collects every feature-specific decision and relevant edge case for the current round
  through native question popups. The context and goal summaries are shown at PRD approval, where
  you correct them if needed;
- **after clarity** → the lead writes the PRD once in plain, skimmable English with a feature title and compact status metadata. A deterministic validator checks the document header, required headings, repetition, sentence length, sequential `AC-xx` acceptance criteria, and that Non-functional requirements lists measurable targets (volume, response time, availability, retention…) or says None explicitly. It does not impose a word-count ceiling. IDs are not used elsewhere. The engine runs the validator when the writer hands off; a defect sends the PRD back to that same writer with the validator's report, a bounded number of times.

The PRD stage never scans application source, and spawns a subagent only to normalize a client
PRD, so a long document stays out of the lead's context. It reads only repository
instructions, maintained project docs, the run's requirement folder, and explicit references.
Pinned skills are checked only under `.agents/skills`, `.claude/skills`, and `.cursor/skills`.
Step durations are recorded in the run ledger so slow stages are visible.

Every run states its change type when it starts (`path=major` or `path=minor`); nothing is
inferred. **Major** is a full PRD and a full plan. **Minor** is a small, contained change: a mini
PRD (problem, acceptance criteria, out of scope) and a plan of 5-10 lines. When the first
preparation of a minor PRD finds nothing to ask, the mini PRD is written and the run moves on
without the PRD approval; any interview round keeps the approval.

The plan stage opens a conversation with the architect. You lead it: the architect reads the
approved PRD, the decision log, `docs/architecture.md` and the codebase maps, then suggests,
names issues and challenges with evidence, one topic per turn. When you say you are done it
writes the agreed direction, decisions and open points to `decisions/brainstorm.md` and asks
whether to write the plan; *Keep talking* goes back to the conversation.

The plan is one document in the workspace root, `docs/plans/active/<slug>.md`, not in the run
folder: it outlives the run. A major plan has a Summary, Decisions (each with its reason and the
rejected alternative, from the brainstorm only), Repositories (every repository it changes, with
the names in `maestro.config.yaml`; a repository to create is marked new), Design (per
repository: modules, data model and migrations, key logic), Interfaces (every call or event
between repositories with its exact shape — method, path, fields, errors — or None),
Infrastructure (or None), Risks and open points, Acceptance coverage (every PRD `AC-xx` mapped to
a repository and component) and Out of scope. A minor plan is the title, a header line and
*Change / Where / Interface / Data / Tests / Risk* lines. The engine checks the structure for the
type (`plan_doc.py validate`) when the writer hands off and sends a defect back with its report.
Every write of the plan is committed in the workspace root on the current branch, with only the
plan file in the commit; it is never pushed.

Infrastructure ships with the feature: a change to queues, config, deployment or cloud resources
goes in the plan's Infrastructure section and names the repository that owns it, which is then
built, verified (with the repository's own `terraform validate`, `helm lint`… from
`maestro.config.yaml`) and reviewed like application code. `maestro.config.yaml` can mark a
repository `role: infra`.

A person approves the plan in every run mode. The choices are *Approve*, *Revise* (say what to
change; only that is edited), *Rethink* (back to the conversation, then a rewrite), *Later* (the
run pauses here and keeps everything; `/maestro <slug>` asks the same question again) and
*Reject*. Approval records the exact PRD and plan hashes and the repositories in scope; once the
test cases are written they are bound to the same approval.

From there Maestro starts or resumes the run, dispatches each remaining step with its declared
execution mode, asks you at gates, and reports where every artifact landed.

Before design, Maestro fetches every discovered repository's **current branch upstream in
parallel**. If everything is current, this is silent and uses no model. If a repository is
behind/diverged, living docs are stale, or an existing feature's pinned commit moved, one
consolidated gate shows the whole workspace. On approval Maestro uses `--ff-only` semantics
for clean behind branches, never stashes/rebases/merges dirty or diverged work, refreshes only
affected knowledge (Sonnet, only when provenance requires it), then pins the exact repository
SHAs in `.maestro/runs/<slug>/.engine/workspace-lock.json`. The same check runs before implementation;
if code moved after design, the design is regenerated and re-approved before build work starts.

Gate choices that require text are deliberately two-stage. Clicking **Revise** first records
the choice, then Maestro asks what to change and remains parked until non-blank feedback is
provided. No artifact is regenerated with empty or inferred suggestions.

The functional test cases are their own stage (`design-tests.yaml`), written from the approved
PRD alone, at the same time as the plan, for both change types. They
are black-box: the acceptance criteria decide which cases exist and what each should observe, in
the PRD's terms, with no status codes or field names the PRD does not state. So a design change
never rewrites them. The engine checks that every PRD acceptance criterion (`AC-xx`) is traced by
at least one case and that no case traces a criterion the PRD lacks, and sends the catalog back
with the exact gaps otherwise; the stage has no approval gate, and only a trace the writer cannot
fix stops for you. QA takes the exact values to
check (status codes, error codes, fields, messages) from the approved plan when it runs each
case; a design that cannot meet a case fails it.

Delivery starts by checking the approval: a PRD, plan or test-case catalog edited after approval
(also outside the run) sends the run back through design, with the reason, instead of being
built stale.

After plan approval, Maestro implements every repository the plan names, in
parallel. If the release is sent back to design, the next delivery pass rebuilds every repository
against the revised design; the pre-implementation workspace drift check still protects stale
designs. That check sends the run back to design when a sync moved a repository's commits after
approval and a changed file is one the plan cites or a migration; the plan is then revised with
the reason and approved again. Keep the current commits at that gate unless you need the updates; set
`design.sync_restart: always` (maestro.config.yaml) to redo the design for any moved commit.

Each repository's code is reviewed by a fresh reviewer that did not write it. The reviewer records
each finding in a findings file and the engine — not the reviewer's own verdict — decides what
blocks. The fixer answers every blocking finding: fixed (an edit), contested (with evidence, which
the reviewer then withdraws or upholds — once) or escalated to you. Each re-review sees only what
changed since its last round, and the loop is bounded by the engine: after three reviews
(`reviews.max_rounds` in maestro.config.yaml), or for a blocking finding first raised on a
re-review that the fix did not cause, the open findings go to you instead of another round.

QA tests exactly those verified commits. When `maestro.config.yaml` defines an `environment`, the
engine starts it before QA (with each repository's worktree and commit in environment variables,
so the stack is built from the code under test) and stops it afterwards. When a repository has
an `e2e` command (confirmed at init or sync), the QA agent automates the test cases in that
framework and runs them; when none does, it checks each case directly against the running system
and adds no framework. Then the engine runs each repository's own `e2e` command in its
worktree. A test-harness failure gets a bounded fix. A **product bug** never stops at a gate: the
QA fixer writes a diagnosis (`qa/bugs.md`) naming the repositories, each is fixed on its own
feature branch with a regression test, re-verified by the engine and re-reviewed (only the new
diff), and QA runs again on the new commits — up to three QA rounds, then you decide.

After QA, the engine joins each criterion to its test cases and their QA results (QA records a
result per case) in `release/ac-trace.md`: passing only when a case for it ran and every case that ran
passed; otherwise failing or not run. The release gate and the review pack show it.

Then a fresh reviewer compares every verified commit with the approved plan — its Interfaces,
Decisions, data and migrations, Infrastructure and the repositories in scope — and records each
place the code departs from it. The engine decides what blocks; blocking drift is shown at the
release gate and stops an autopilot release.

If a change to an already-approved PRD or plan comes up mid-run, Maestro records it
as a note and offers two paths: revise the design (at the current design gate, or by sending the
release back to design once past design), or reject or defer the change. Design documents are
never edited out of band.

Prefer manual control? Every step is also a skill you can invoke on its own — use its slash
command in Claude Code/Cursor or mention it with `$` in Codex (`/plan-writing` or
`$plan-writing`, for example). Same skills, no orchestration.

**One stage under Maestro.** Start a stage's own workflow on an existing feature slug:
`/maestro <slug> .maestro/workflows/design-plan.yaml path=major` (or `path=minor`) or
`design-tests.yaml` (the functional test cases). Both need `requirement/prd.md`; Maestro checks
it first and names what is missing. A slug that already has a run ledger is replaced only after
you confirm, and the old ledger is kept as `.engine/ledgers/replaced-<time>.yaml`.

**A skill on its own.** Without Maestro, give `/plan-writing` your inputs in the message: the
feature, the change type, the PRD, any brainstorm notes, the repositories and where to write the
plan, for example

```
/plan-writing
Feature: phone-otp-login (major)
Inputs: PRD at docs/prd/phone-otp-login.md, notes in docs/notes/otp-brainstorm.md.
Repositories: auth-service, web-app.
Write the plan to docs/plans/active/phone-otp-login.md.
```

The skill writes the plan in the same template and skips the workflow-only pieces (the engine's
check, the commit, the approval record).

## Where a feature's files are

The plan is not in the run folder: it is `docs/plans/active/<slug>.md` in the workspace root
while the feature is built, and `docs/plans/completed/<slug>.md` once it is archived.

The run keeps one folder per feature, grouped by kind. Open `requirement/`, `design/`, `decisions/` and
`reviews/` to read what was asked, designed, decided and found; `.engine/` is the engine's own
working space.

```
.maestro/runs/<slug>/
├── state.yaml      the run ledger (engine only)
├── requirement/    what was asked: your files, prd.md
├── design/         test-cases.md; a bug's fix-proposal.md
├── decisions/      what was decided: decision-log.md (unconfirmed decisions first), the PRD
│                   interview record (prd.json), brainstorm.md
├── reviews/        what reviewers found: <name>.md, <name>.findings.json and the author's
│                   <name>.resolutions.json (drift, code-<repo>)
├── build/          what was built: manifest.json, <repo>/tasks.json, <repo>/verify.json
├── qa/             how it was tested: the suite, report.md, results.json
├── release/        what ships: review-pack.md, ac-trace.md, delivery.json, plan-changes.md
└── .engine/        question queues, review baselines, sync plans, snapshots, logs, replaced
                    ledgers, the debug profile
```

Each fact is stored once. A decision lives in its stage's record, and the decision log is its
rendering; a re-review compares against one baseline file per review under `.engine/reviews/`
(the documents as the last round saw them), not copies of the documents.

A run started before this layout is moved into it the next time it is resumed
(`maestroctl migrate --slug <slug> --dry-run` shows what would move): files are moved, never
rewritten. A run designed with the earlier HLD and LLD stages cannot continue under this
version: finish it with the version that started it, or start it again with `init --force`.

## New products (greenfield)

A workspace with no repositories yet takes the greenfield path. The brainstorm decides which
repositories to create — one per deployable service or shared library — and their stacks, and the
plan lists them in its Repositories table marked new. Once the plan is written, and before you
approve it, the engine creates each repository, a scaffolding agent gives it a passing build and
test, lint, a README, CI, a container image or starting infrastructure when the plan deploys one,
and a codebase map (`docs/codebase-maps/<name>.md` in the workspace); the engine adds their
commands to `maestro.config.yaml`, runs them once to prove the skeleton works, and pins the new
commits. Delivery then runs on the new repositories exactly as on existing code.

## Fixing a bug

`/maestro <slug> bugfix branch=<branch>` runs `bugfix.yaml`, for a bug seen on `<branch>`. There is
no plan and no implementation pass:

```
workspace sync → pin the bug down with you (a conversation; the bug report becomes a mini PRD
   whose acceptance criteria are the expected behaviours) → functional test cases
   → [reproduce first, or skip?] → branch in every affected repository?
       → [missing: use the repository's default branch / name another / drop the repository]
   → sandbox: a worktree per affected repository on fix/<slug>-<repo>, off its base
   → [reproduce: start the app on the sandbox → a failing regression test → stop the app
       → not reproduced? proceed / tell me more / reject]
   → fix proposal (root cause, change per repository, impact, risks, tests) → [approve the fix]
   → fix each repository in its sandbox worktree → QA → trace → review pack → [approve release]
   → [confirm archive] → branches or pull requests, each against its repository's base
```

Put any bug report files in `.maestro/runs/<slug>/requirement/` first; without them the triage
starts from your description. Every gate in the triage asks a person, in every run mode; *Later*
at the fix approval pauses the run and keeps the sandbox. Without `environment.start` in
`maestro.config.yaml` the reproduction is a failing test only. The reproduction report
(`qa/reproduction.md`) names each repository's branch and commit, so a mix of bases is visible.
The configured `worktree.create` command needs the `{branch}` placeholder to build the sandbox on
the right base. Anything delivery or the release sends back returns to triage with the reason.
The triage runs on its own as `bugfix-triage.yaml branch=<branch>`.

## Run modes

Say how much you want to be asked when you start a feature ("run it on autopilot", "only stop
for design approval"). The mode decides who answers each gate:

| Gate | `human` (default) | `design` | `auto` |
|---|---|---|---|
| PRD approval | you | you | approved |
| Brainstorm and "write the plan?" | you | you | you |
| Plan approval | you | you | you |
| Workspace updates | you | keep current commits, refresh stale docs | same |
| Release | you | approved if the engine verified every repository, every acceptance criterion passes QA, there is no blocking drift and no blocking or major review finding is open | same |
| Archive confirmation, plan changes | you | you | you |
| Bug triage, reproduction and fix approval | you | you | you |
| PRD questions | you | you | recommendation adopted as an assumption; one round |
| Missing requirement, question limit, stuck fix loop, failing QA | you | you | you |

The brainstorm, the plan approval and the archive confirmation always ask a person, in every
mode, so even `auto` stops for them. Before archiving, the engine checks the release record (`release.json`, written when the release is approved): the archive refuses a
feature whose release was not approved, or whose code changed since. Archiving delivers the verified
branches (or opens pull requests), harvests the run's lessons into `.maestro/memory/`, refreshes
the living docs under `docs/` and removes the worktrees Maestro created. Before the plan is
filed, the architect compares it with the delivered commits (starting from the drift report);
when they differ you choose to file the updated plan, keep the plan as approved (the differences
stay in `release/plan-changes.md`), or edit the update. The plan then moves to
`docs/plans/completed/<slug>.md` and that move is committed. If you choose "Not now",
nothing is pushed (push the branches yourself, from the implementation manifest) and the updated
documents do not reach `docs/`; the worktrees are kept and the plan stays active. Archive later with
`/maestro <feature> .maestro/workflows/archive.yaml`.

Each gate's policy lives in the workflow (`auto:` on the gate), and the engine applies it — the
lead agent never answers a gate. A gate whose check fails stops the run for you, with the reason;
the ledger and `maestroctl status` mark every autopilot decision. `auto` will not start until
`maestroctl preflight` passes, since the engine's own build and test runs are what stand in for
your review. Change the mode of a running feature by asking Maestro to switch; it applies from
the next gate.

In `auto` mode nobody answers the PRD interview: each recommendation is recorded as an assumption,
a question with no grounded recommendation is left open rather than guessed, and each stage asks
once. The decision log opens with every assumption, open item and autopilot gate decision
(including assumptions a person chose in any mode) under "Not confirmed by a person"; it is
rendered again before the review pack, which opens with that section.

## Interviews are conversations

Every PRD decision lands in one decision log per feature
(`.maestro/runs/<slug>/decisions/decision-log.md`), shown at each design approval. The log is
rendered from each stage's interview record beside it (`prd.json`), the only place a decision is
stored. A later stage never
re-asks a topic an earlier one decided — the engine checks each question's topic against those
records — and a decision gets at most one follow-up. Before asking, Maestro records what the requirement,
approved documents, code or docs already settle, citing the source, instead of asking you.

PRD questions are not a form to fill in. Each popup question offers:

- **the recommendation**, with why it matters;
- **up to two alternatives**, each with its concrete trade-off;
- **Not sure — let's discuss**, when you don't know the answer yet;
- **free text**, for your own answer or a side question ("btw, how does billing handle this today?").

The last popup of each round also asks **Anything to add?**, so you can raise what Maestro missed.

**Drilling down without polluting the run.** When you're unsure, the discussion happens outside
the lead agent's context, so a long side conversation can't crowd out a long pipeline:

| Mode | How | What reaches the lead |
|---|---|---|
| **Isolated subagent** (default) | A read-only `discussant` subagent gets an engine-rendered brief: the question, alternatives, the facts an answer must settle, and the evidence it may read. It does all the reading and reasoning. | Its short replies (≤120 words), relayed verbatim, plus a one-line outcome |
| **Side chat** (deep dives; always in Cursor) | Say *take it to a side chat*. Maestro saves the round's other answers and shows a command such as `/maestro-discuss my-feature design/prd/prd_interview export-retention` (`$maestro-discuss` in Codex). Run it in a new chat, settle the question there, then say *continue* in the main chat. | Nothing but the recorded outcome |

Every discussion ends with you choosing the outcome. If you still can't settle it, adopt the
recommendation as a **working assumption** (the document marks it unverified) or **park it** as an
open item (it is never treated as decided). Points you raise are recorded in your own words, and
the next round must account for them.

**No question without a real choice.** A stage asks only what the approved documents, the decision
log, the code and the docs leave open; when they settle everything it asks nothing and writes the
document, which you still review at its approval gate. A round you accept as recommended goes
straight to writing — only a typed answer, a chosen alternative, a parked item or a point you
raise brings a follow-up round.
At an approval gate you can also ask about the document ("why one service?") instead of choosing;
Maestro answers from that document only and asks the gate again.
