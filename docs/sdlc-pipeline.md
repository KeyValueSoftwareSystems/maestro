# The included SDLC pipeline

Maestro ships one complete example workflow, `.maestro/workflows/sdlc-main.yaml`. This page
explains what it does at each stage. To run it, see the [README](../README.md#start-your-first-feature).

## The stages

Shipped as a worked example (`.maestro/workflows/sdlc-main.yaml` + the installed skills
pack) — a full AI-SDLC pipeline you can run today and fork into your own:

```
workspace sync → requirement → PRD (summarize context → Grill unclear decisions → write once → validate)
   → HLD (Grill architecture with options → confirm direction → write once → validate
          → architecture review by a fresh reviewer → [approve])
   → API contract (only when the HLD lists cross-repo interfaces)
   → repository LLDs, one run (one grouped Grill → write one LLD per repo → validate
          → readiness check → functional test cases (every AC traced) → [approve])
   → design still current? → implement every repo (parallel, sliced,
     engine-verified build/lint/test, reviewed)
   → QA (product bug → fix that repo, re-verify, re-review → QA again)
   → acceptance-criteria trace → design-vs-code drift check → assumption log → review pack
   → [approve] → branches or pull requests (per config) → harvest lessons
```

**Roles.** Each step is done by a role, and the workflow fixes the order in which work passes
between them; no model chooses who goes next.

| Role | Jobs in the shipped pipeline |
|---|---|
| `product` | intake context; prepare the feature goal and product questions; write and revise the PRD |
| `architect` | impact assessment; HLD questions, the HLD and its revisions, answers to the architecture review; the contract; LLD questions, the LLDs and their revisions |
| `reviewer` | architecture review, LLD readiness, code review, design drift |
| `implementer` (developer) | the task plan, the code, fixes from verification and review; scaffolds new repositories |
| `qa` | the functional test cases; the automated QA run and test-harness fixes |
| `analyst` | knowledge refresh, the review pack, the retrospective |

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
`Design phase › HLD — waiting on you: HLD approval`. The same checklist is one command away in any
terminal:

```
$ python3 .maestro/engine/maestroctl.py todo --slug my-feature
my-feature · sdlc-main · running
[x] Workspace sync (feature start)
[>] Design phase
    [x] Requirement and context
    [x] PRD
    [?] HLD
          ↳ waiting on you: HLD approval
    [ ] Repository LLDs
    [ ] API contract and test cases
[ ] Design review
[ ] Implementation, QA and release
[ ] Pull requests and archival
```

On first run the lead agent scaffolds `.maestro/runs/my-feature/requirement/`. Drop any requirement files in there (PRDs, tickets, notes, reference links — every file is read); the shipped pipeline then **builds a PRD** (`requirement/prd.md`) before the HLD:

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
- **after clarity** → the lead writes the PRD once in plain, skimmable English with a feature title and compact status metadata. A deterministic validator checks the document header, required headings, repetition, sentence length, sequential `AC-xx` acceptance criteria, and that Non-functional requirements lists measurable targets (volume, response time, availability, retention…) or says None explicitly. The architecture review later checks the HLD meets each target. It does not impose a word-count ceiling. IDs are not used elsewhere. The engine runs the validator when the writer hands off; a defect sends the PRD back to that same writer with the validator's report, a bounded number of times.

The PRD stage never scans application source, and spawns a subagent only to normalize a client
PRD, so a long document stays out of the lead's context. It reads only repository
instructions, maintained project docs, the run's requirement folder, and explicit references.
Pinned skills are checked only under `.agents/skills`, `.claude/skills`, and `.cursor/skills`.
Step durations are recorded in the run ledger so slow stages are visible.

Infrastructure questions depend on the workspace, not on a checklist. Before the HLD questions,
the engine scans every repository (and an umbrella workspace's root) for infrastructure
definitions and sets a level:

| Level | Found | What the HLD asks |
|---|---|---|
| `none` | no infrastructure definitions | no infrastructure questions; scale is handled inside the application design when a target needs it |
| `containers` | Dockerfiles or Compose files only | only the runtime and config decisions this feature changes (a new service, ports, secrets, resources) |
| `iac` | Terraform, Helm, Kubernetes, Pulumi, CDK, CloudFormation, Serverless or Ansible | every infrastructure decision this feature changes or depends on — scaling, data stores, queues, caching, networking, secrets, rollout, observability, cost — grounded in those repositories and the PRD's targets |

A feature that touches no infrastructure asks none at any level. Infrastructure ships with the
feature: each change in the HLD names the repository that owns it, those repositories cannot be
dropped from the LLD scope, and a new service lists its container image, CI pipeline and deployment
definitions, which are designed, built, verified (with the repository's own `terraform
validate`, `helm lint`… from `maestro.config.yaml`) and reviewed like application code. `maestro.config.yaml` can
override the level (`infrastructure.level`, for example when another team owns it) or mark a
repository `role: infra`. The architecture reviewer reviews infrastructure only at the levels
that have it, and the readiness check makes each listed infrastructure change an LLD in the
repository that owns it. The HLD writer and reviewer draw on the `architecture-patterns` skill
and, per detected platform, the `terraform-patterns`, `kubernetes-patterns` and
`container-patterns` packs (installed by `detect-stack` when the workspace uses them).

The HLD stage follows the same clarify-first shape. It batches only unresolved architecture
decisions into native question popups, each with real alternatives and their trade-offs, then asks
you to confirm the assembled design direction before anything is written (see
[Interviews are conversations](#interviews-are-conversations)). It keeps decisions in
`hld-context.json` and writes one short, plain-English HLD. A deterministic validator checks its seven-section structure (including an Interfaces list that decides whether a contract step runs, an Infrastructure and operations section when the workspace defines infrastructure, and a Mermaid diagram whenever the feature crosses repositories or changes infrastructure),
readability, repetition, and deferred-question ledger without limiting document length. A second popup appears only when synthesis
uncovers a genuinely new architecture gap; there is no mandatory model-powered folding pass.
`open-questions.json` contains only explicitly deferred decisions so another reviewer can see
what remains open.

From there Maestro starts or resumes the run, dispatches each remaining step with its declared
execution mode, asks you at gates, and reports where every artifact landed.

Before design, Maestro fetches every discovered repository's **current branch upstream in
parallel**. If everything is current, this is silent and uses no model. If a repository is
behind/diverged, living docs are stale, or an existing feature's pinned commit moved, one
consolidated gate shows the whole workspace. On approval Maestro uses `--ff-only` semantics
for clean behind branches, never stashes/rebases/merges dirty or diverged work, refreshes only
affected knowledge (Sonnet, only when provenance requires it), then pins the exact repository
SHAs in `.maestro/runs/<slug>/workspace-lock.json`. The same check runs before implementation;
if code moved after design, the design is regenerated and re-approved before build work starts.

Gate choices that require text are deliberately two-stage. Clicking **Revise** first records
the choice, then Maestro asks what to change and remains parked until non-blank feedback is
provided. No artifact is regenerated with empty or inferred suggestions.

The HLD is reviewed before it is approved. A fresh reviewer agent — one that did not write it —
checks the architecture against the requirement: style, boundaries and data ownership, the
listed interfaces, security, failure handling, scale, operations, and over- or
under-engineering. Blocking findings go back to the HLD author for targeted edits and a
re-review; you see the review next to the HLD at approval. The reviewer records each finding in a
findings file and the engine — not the reviewer's own verdict — decides what blocks. The HLD author
answers every blocking finding: fixed (an edit), contested (with evidence, which the reviewer
then withdraws or upholds — once) or escalated to you. An escalation, or a second contest of an
upheld finding, stops at HLD approval with the question stated. The LLD readiness check and the
code reviews work the same way. Each re-review sees only what changed since its last round (the
engine hands it the diff), and the loop is bounded by the engine: after three reviews
(`reviews.max_rounds` in maestro.config.yaml), or for a blocking finding first raised on a
re-review that the revision did not cause, the open findings go to you at the stage's gate
instead of another round. A wrong architecture call found here
costs one document edit instead of a redo of the contract, LLDs and code.

The HLD's Interfaces section lists every call or event between repositories, or says None. When
it lists any, a contract step defines them (OpenAPI, or AsyncAPI for events) following the owning
repository's existing conventions, before any LLD is written, so every repository builds against
one version.

All repository LLDs are written in one run: one grouped popup of code-grounded questions across
the repositories in scope, then one LLD file per repository (`lld/<repo>.md`), so each
implementation agent later reads only its own repository's design. Each LLD implements or calls
the contract exactly. If a repository needs something the contract lacks — for example a field
the frontend needs — the LLD writer reports it, the contract is updated first, and every
affected LLD is revised. Then a readiness check by a fresh reviewer: no design decision left to
the implementer, every LLD consistent with the contract and with each other, every acceptance
criterion covered by an LLD. Once the LLDs pass it, the functional test cases are written once
(not on every revision round); the engine checks that every PRD acceptance criterion (`AC-xx`) is
traced by at least one case and that no case traces a criterion the PRD lacks, and sends the
catalog back with the exact gaps otherwise. One approval covers all of them.

Approval records the exact HLD, contract and LLD hashes. Delivery starts by checking them: a
design that changed after approval goes back through design instead of being built stale.

After LLD approval, Maestro implements every repository in the approved design, in
parallel. If the release is sent back to design, the next delivery pass rebuilds every repository
against the revised design; the pre-implementation workspace drift check still protects stale
designs.

QA tests exactly those verified commits. When `maestro.config.yaml` defines an `environment`, the
engine starts it before QA (with each repository's worktree and commit in environment variables,
so the stack is built from the code under test) and stops it afterwards. The QA agent automates
and runs the test cases; then the engine runs each repository's own `e2e` command in its
worktree. A test-harness failure gets a bounded fix. A **product bug** never stops at a gate: the
QA fixer writes a diagnosis (`qa/bugs.md`) naming the repositories, each is fixed on its own
feature branch with a regression test, re-verified by the engine and re-reviewed (only the new
diff), and QA runs again on the new commits — up to three QA rounds, then you decide.

After QA, the engine joins each criterion to its test cases and their QA results (QA records a
result per case) in `ac-trace.md`: passing only when a case for it ran and every case that ran
passed; otherwise failing or not run. The release gate and the review pack show it.

Then a fresh reviewer compares every verified commit with the approved HLD, contract and LLDs —
contract, design decisions, data and migrations, infrastructure, scope — and records each place the
code departs from the design. The engine decides what blocks; blocking drift is shown at the
release gate and stops an autopilot release.

If a change to an already-approved PRD, HLD, contract or LLD comes up mid-run, Maestro records it
as a note and offers two paths: revise the design (at the current design gate, or by sending the
release back to design once past design), or reject or defer the change. Design documents are
never edited out of band.

Prefer manual control? Every step is also a skill you can invoke on its own — use its slash
command in Claude Code/Cursor or mention it with `$` in Codex (`/hld-writing` or
`$hld-writing`, for example). Same skills, no orchestration.

## New products (greenfield)

A workspace with no repositories yet takes the greenfield path. The HLD questions then decide
which repositories to create — one per deployable service or shared library — and their stacks,
and the HLD lists them in a Repositories section (`` `name` (stack): purpose ``). After you approve
the HLD, the engine creates each repository, a scaffolding agent gives it a passing build and test,
lint, a README, CI, a container image or starting infrastructure when the design deploys one, and
a codebase map (`docs/codebase-maps/<name>.md` in the workspace); the engine adds their commands to `maestro.config.yaml`, runs them once to prove the
skeleton works, and pins the new commits. The contract, LLDs and delivery then run on the new
repositories exactly as on existing code.

## Light path for small changes

After PRD approval an impact assessment (skill `feature-impact`) names the repositories the
feature changes and whether it changes an interface between them, stored data or infrastructure;
the engine checks every name is a repository the workspace has. The engine then sizes the
feature from that, not from how many repositories the workspace holds. A small change — at most
five acceptance criteria (`design.light_max_criteria` in maestro.config.yaml), no non-functional
targets, exactly one repository changed, no interface or infrastructure change, nothing left
"(to confirm)" — skips the HLD and the API contract: PRD → repository LLD (which carries the ownership, failure
and rollout notes an HLD would) → readiness check → test cases → approval → delivery. Everything
else takes the full path. Start a run with `path: full` or `path: light` to choose yourself
(`init --input path=light`). The approval binds the PRD's hash, so a PRD edited after approval is
still caught before delivery.

## Run modes

Say how much you want to be asked when you start a feature ("run it on autopilot", "only stop
for design approval"). The mode decides who answers each gate:

| Gate | `human` (default) | `design` | `auto` |
|---|---|---|---|
| PRD approval | you | you | approved |
| HLD approval | you | you | approved if the architecture review has no blocking findings |
| LLD scope | you | the repositories the impact assessment names (plus infrastructure owners) | same |
| LLD approval | you | approved if the readiness check passes | same |
| Workspace updates | you | keep current commits, refresh stale docs | same |
| Release | you | approved if the engine verified every repository and every acceptance criterion passes QA | same |
| PRD, HLD and LLD questions | you | you | recommendation adopted as an assumption; one round |
| Missing requirement, question limit, stuck fix loop, failing QA | you | you | you |

Each gate's policy lives in the workflow (`auto:` on the gate), and the engine applies it — the
lead agent never answers a gate. A gate whose check fails stops the run for you, with the reason;
the ledger and `maestroctl status` mark every autopilot decision. `auto` will not start until
`maestroctl preflight` passes, since the engine's own build and test runs are what stand in for
your review. Change the mode of a running feature by asking Maestro to switch; it applies from
the next gate.

In `auto` mode nobody answers the interviews: each recommendation is recorded as an assumption,
a question with no grounded recommendation is left open rather than guessed, and each stage asks
once. Before the review pack, `assumptions.md` lists every assumption, open item and autopilot gate
decision (including assumptions a person chose in any mode); the pack opens with it.

## Interviews are conversations

Every PRD, HLD and LLD decision lands in one decision log per feature
(`.maestro/runs/<slug>/decision-log.md`), shown at each design approval. A later stage never
re-asks a topic an earlier one decided — the engine checks each question's topic against the log —
and a decision gets at most one follow-up. Before asking, Maestro records what the requirement,
approved documents, code or docs already settle, citing the source, instead of asking you.

PRD, HLD and LLD questions are not a form to fill in. Each popup question offers:

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
| **Side chat** (deep dives; always in Cursor) | Say *take it to a side chat*. Maestro saves the round's other answers and shows a command such as `/maestro-discuss my-feature design/hld_interview cache-owner` (`$maestro-discuss` in Codex). Run it in a new chat, settle the question there, then say *continue* in the main chat. | Nothing but the recorded outcome |

Every discussion ends with you choosing the outcome. If you still can't settle it, adopt the
recommendation as a **working assumption** (the document marks it unverified) or **park it** as an
open item (it is never treated as decided). Points you raise are recorded in your own words, and
the next round must account for them.

**You see the design before it's written.** HLD and LLD rounds end with a *direction* question:
a short summary of the whole intended design for you to confirm, challenge or discuss. The engine
won't let the queue close until the latest direction is confirmed after every other decision.
At an approval gate you can also ask about the document ("why one service?") instead of choosing;
Maestro answers from that document only and asks the gate again.
