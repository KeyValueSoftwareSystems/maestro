---
name: hld-interview
description: Clarify material architecture decisions before an HLD is finalized. Generate feature-specific technical Grill questions, audit prior answers and contradictions, and collect grouped answers without drafting design prose.
allowed-tools: Read, Grep, Glob, Write, Bash
tags: [sdlc, design, hld]
---

# HLD interview

Resolve architectural direction before prose. This skill runs in the lead agent's context so
questions remain connected to the approved product decisions; never delegate the conversation.
The one exception is discussing a single question the user is unsure about: that runs in an
isolated discussion agent or a side chat, under this skill's read boundary and design-conversation
rules, so its reading never fills the lead's context.

## Read boundary

Read only workflow-supplied requirements, decision artifacts, revision feedback, project guidance,
maintained codebase maps, and source files whose detail is necessary for a material decision the
maps do not settle. Do not scan application source broadly or search outside the repository.

## Architecture Grill

Ask only decisions that change the approved direction or what a downstream LLD must respect:

- system and repository ownership;
- service, module, and trust boundaries;
- source of truth and major data lifecycle;
- cross-repository control or data flow;
- authentication, authorization, privacy, and sensitive-data exposure;
- failure, recovery, idempotency, concurrency, and relevant execution modes;
- compatibility, migration, rollout, backout, and material operational trade-offs.

Do not ask about PRD scope already settled. Do not ask for endpoint fields, table columns, class or
file names, library syntax, task breakdowns, or other LLD choices. Recommend the simplest direction
grounded in the approved requirement and existing architecture.

**Infrastructure questions follow the workspace, not a checklist.** When your instructions supply
an infrastructure profile, its level decides:

- **none** — the workspace defines no infrastructure: ask no deployment, scaling-topology or
  platform questions. Scale is answered inside the application design (caching, async work,
  pagination) only when a non-functional target needs it.
- **containers** — ask only the runtime and configuration decisions this feature changes: a new
  service or process, ports, config and secrets, resource limits.
- **iac** — the workspace holds infrastructure as code: read those repositories and ask every
  material infrastructure decision this feature changes or depends on — scaling (instances and
  autoscaling triggers), data-store capacity and topology, queues and topics, caching, networking
  and ingress, config and secrets, environments and rollout, observability (SLOs, alerts), and
  cost. Ground each recommendation in what the infrastructure already provisions and in the
  requirement's non-functional targets.

At every level, a feature that changes and depends on no infrastructure asks none. Without a
profile, ask infrastructure questions only when the repositories you read define infrastructure.

## Design conversation

Architecture is decided with the user, not announced to them.

- **Write for a quick read.** The person answers many questions in a row, so each must be clear on
  the first pass: one plain sentence that ends in a question mark, everyday words, the concrete
  situation first ("When a code expires while the user is typing it, …"). No internal IDs, file
  paths or acronyms the user has not used; no "and/or", brackets or nested clauses. Keep `title`
  to a few words naming the decision, `why` to what changes for the system or its cost to change,
  and the recommendation to the answer itself, stated first, with at most one sentence of reason.
  Option labels are short answers that can be chosen without reading the trade-off.
- For every genuine trade-off, offer the recommendation plus up to two real `alternatives`
  (`{label, tradeoff}`) with their concrete consequences — cost, coupling, failure behavior,
  migration risk. Never invent a straw option to make the recommendation look good.
- When the queue asks anything, end it with one `kind: "direction"` question. Its `proposal` (up
  to 150 words) summarises the intended architecture — owners, boundaries, main flow, and the key
  trade-offs taken, assuming each recommendation is accepted — so the user confirms, challenges,
  or discusses the whole shape before prose is written. Once the user has answered anything, the
  queue cannot close until a direction is confirmed no earlier than their last answer; ask a
  fresh direction (new ID) only when a later answer changes it. When there is nothing to ask,
  ask no direction either.
- When the user is unsure or asks back, explain the reasoning, compare options, and answer from
  the requirements, maintained maps, and the specific source that settles it. Say what you
  checked. If a fact belongs to someone else, offer a working assumption or deferral.
- Invite the user's own concerns; treat a `user-raised` point as a constraint to reconcile.

## Answer audit

A saved answer is not automatically complete.

- Compare it with every `must_resolve` fact attached to its question.
- For `source: user-answer`, treat only `answer` as confirmed; unaccepted proposal text is not a
  decision. `chosen-alternative` and `accepted-proposal` are confirmed; `assumption` is a working
  answer to flag as unverified; `deferred` settles nothing; `user-raised` is the user's own input.
  Build on a `discussion` summary instead of re-asking what was explored.
- A deferred blocking decision must be re-asked with sharper options; a deferred non-blocking one
  goes to LLD.
- Compare decisions for conflicting ownership, authority, state boundaries, timing, failure
  behavior, or execution-mode assumptions.
- Follow up only on the missing or conflicting fact and use a new stable ID.
- Treat concrete product rules from the PRD as constraints, not questions to reopen.
- A user may explicitly defer a non-blocking implementation choice to LLD. Preserve that answer;
  never describe a blocking architectural decision as safe to defer.

## Queue contract

Write the workflow-supplied queue as `schema_version: 2` with `questions` and `audit`. Each question
has `id`, `title`, `question`, `why`, `proposal`, and one to four short `must_resolve` facts; it may
add `alternatives` and `kind` (`decision` by default, or `direction`).
`audit.unresolved` and `audit.contradictions` name why another round exists. Both arrays are empty
only when the queue is empty and the architecture is clear enough to write. Run the supplied
validator before completing.

**Fewest questions.** There is no minimum, and an empty queue on the first pass is a normal
result. A question earns its place only when the approved requirement, the decision log, the code and the docs do not settle it and reasonable architects
would choose differently at a cost that is high to change after approval. A point with one sensible answer is not a
question: record it under `settled` when a source states it, otherwise design it and let the
document's review check it. Put every material
gap in one queue rather than spreading it over rounds.

**One decision log, no repeats.** Your instructions may supply the feature's decision log (every
earlier stage's decisions) and this stage's decisions. Give every question a short kebab-case
`topic` naming what it decides. Never ask a topic already decided in either; to refine a recorded
answer, ask at most one follow-up with `follow_up_of: <that decision's id>`. Rephrasing a decided
question under a new id is still a repeat.

**Decide from evidence first.** Before asking, check the requirement, approved documents, code and
docs. A point they already settle is not a question: record it under the queue's `settled` array
as `{topic, title, decision, source}`, where `source` is the file that settles it
(`path`, `path#section` or `path:line`). The engine records it as an evidence-settled decision.

## Interview presentation

When the workflow serves a question batch, collect it through the requested native popup. If the
host limits questions per popup, collect consecutive chunks without analyzing or recording between
them. Then discuss the items the user was unsure about or asked about, take any point they raise,
and record the complete round atomically.

## Standards

- One material decision per question; one question mark.
- State why it matters in one short sentence.
- Prefer a concrete recommendation with real alternatives over an abstract menu.
- Never ask questions derived from HLD headings.
- Never draft or edit the HLD in this skill.
- Keep each turn short and let the user steer; no essays between rounds.

When the workflow supplies validator feedback naming defects in an existing queue, fix only those
defects in that file and validate again; do not rebuild the queue or re-read sources.

## Safety

Write only the workflow-supplied question queue. The engine owns durable interview state and the
cumulative decision artifact.

## Output contract

Return `summary`: one short sentence describing the prepared architecture question queue or that
the architecture audit is clear.
