# The included SDLC pipeline

Maestro ships one complete example workflow, `.maestro/workflows/sdlc-main.yaml`. This page
explains what it does at each stage. To run it, see the [README](../README.md#start-your-first-feature).

## The stages

Shipped as a worked example (`.maestro/workflows/sdlc-main.yaml` + the installed skills
pack) — a full AI-SDLC pipeline you can run today and fork into your own:

```
workspace sync → requirement → PRD (confirm context → Grill unclear decisions → write once → validate)
   → HLD (Grill architecture with options → confirm direction → write once → conditional new-gap popup → validate → approve)
   → per-repo LLDs (bounded code seam → grouped Grill with options → confirm direction → write once → validate → approve)
   → API contract
   → functional test cases → effective design (base approvals + approved corrections)
   → architecture review → [approve]
   → choose implementation batch → implement selected repos (parallel, sliced, reviewed)
   → QA → review pack → [approve → archive: fold corrections + harvest lessons + publish docs]
```

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
    [x] Codebase map check
    [?] HLD
          ↳ waiting on you: HLD approval
    [ ] Repository LLDs
    [ ] API contract and test cases
[ ] Design review
[ ] Implementation, QA and release
[ ] Archival (harvest + publish)
```

On first run the lead agent scaffolds `.maestro/runs/my-feature/requirement/`. Drop any requirement files in there (PRDs, tickets, notes — every file is read); the shipped pipeline then **builds a PRD** (`requirement/prd.md`) before the HLD:

- **valid existing `prd.md`** → after two short context confirmations, it goes directly to
  PRD approval; common equivalent headings are accepted because PRDs have no universal format;
- **partial or nothing** → it asks for optional references, confirms a three-sentence project context and two-sentence feature goal, then collects every feature-specific decision and relevant edge case for the current round through native question popups;
- **after clarity** → the lead writes the PRD once in plain, skimmable English with a feature title and compact status metadata. A deterministic validator checks the document header, required headings, repetition, sentence length, and sequential `AC-xx` acceptance criteria. It does not impose a word-count ceiling. IDs are not used elsewhere. Only validation defects trigger one bounded repair.

The PRD stage does not spawn subagents or scan application source. It reads only repository
instructions, maintained project docs, the run's requirement folder, and explicit references.
Pinned skills are checked only under `.agents/skills`, `.claude/skills`, and `.cursor/skills`.
Step durations are recorded in the run ledger so slow stages are visible.

The HLD stage follows the same clarify-first shape. It batches only unresolved architecture
decisions into native question popups, each with real alternatives and their trade-offs, then asks
you to confirm the assembled design direction before anything is written (see
[Interviews are conversations](#interviews-are-conversations)). It keeps decisions in
`hld-context.json` and writes one short, plain-English HLD. A deterministic validator checks its six-section structure,
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

After HLD approval, the parent creates one child run per selected repository—for example
`my-feature--lld--backend`, `my-feature--lld--frontend`, and `my-feature--lld--flutter`—and waits.
Each child inspects only the relevant implementation seam, asks material repository decisions in
one grouped popup with code-grounded alternatives, confirms the repo's change direction with the
team, writes the concise LLD once in the lead session, then runs a deterministic shape
and readability check. A second popup appears only if writing exposes a genuinely new blocking gap;
repair is a narrow fallback only when validation fails. Each team reviews and approves only its
child slug. Approval publishes a hash-bound LLD and receipt into the parent feature; the API
contract cannot start until every selected child is approved against the current HLD.

Architecture review classifies every blocking verdict by its earliest source-of-truth layer and
the exact repositories whose LLDs must reflect the change. The gate always offers an LLD-only fast
path: approving it writes immutable repository correction receipts, preserves the approved PRD and
HLD, creates fresh child ledgers only for the affected repositories, and waits for those LLDs to be
approved again. Maestro then regenerates the contract and test cases and reruns architecture review
before implementation. Choosing source-layer revision instead reopens only the classified layer;
product/cross-cutting findings retain the full-design fallback.

Resuming the parent while those workstreams are pending always opens an LLD selector showing each
repo's status plus a parent-coordinator option. A developer can therefore return with
`/maestro my-feature` and choose backend, frontend, or Flutter without remembering the child slug.

After contract approval, a separate implementation-scope gate chooses all available repositories
or a smaller delivery batch such as backend only. The implementation queue records the complete
designed scope, completed repositories, and deferred repositories independently. After a batch is
reviewed and approved, the parent either archives when nothing remains or parks at a deferred-work
gate. Resuming that gate can implement another batch without rerunning PRD, HLD, LLD, contract, or
architecture review; the normal pre-implementation workspace drift check still protects stale
designs.

If implementation discovery changes an already-approved product or architecture decision, Maestro
offers two explicit paths: revise the base documents now, or record the human-approved decision as
an **approved correction** and continue. Each correction is a separate merge-friendly receipt;
the engine renders all receipts into `approved-corrections.md` and `effective-design.json`, which
override conflicting base text for every downstream phase. Archive folds them once into validated
`final-design/` copies while preserving the original hash-bound approvals.

Prefer manual control? Every step is also a skill you can invoke on its own — use its slash
command in Claude Code/Cursor or mention it with `$` in Codex (`/plan` or `$plan`, for
example). Same skills, no orchestration.

## Interviews are conversations

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
