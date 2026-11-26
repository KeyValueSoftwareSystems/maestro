---
name: system-design
description: Designs a software change against the existing codebase. Use when a change adds or alters components, APIs, data schemas or cross-service flows, after the requirements are settled and before planning. Not for building an already-designed change or for small fixes.
# REVIEW: system-design A5: added "Not for..." so it doesn't load on every coding task. A7: shortened the "what" so agents don't follow the summary and skip the body.
---

# System design

Write the design into the plan you are writing: Interfaces into its Contracts section and Rollout
into its Rollout section when it has them, and the rest into Design. With no plan, write it to
`design.md` in the current directory.
<!-- REVIEW: system-design D2: the plan has separate Contracts and Rollout sections, so Interfaces and Rollout landed twice or in the wrong place. -->

## How
1. **Constraints.** From the requirements, take load, latency, data size, consistency,
   compatibility, security and deadlines, each with a number where it shapes the design. From the
   code, take the existing patterns, frameworks, data stores and conventions.
2. **Options.** Spend effort in proportion to how hard a decision is to undo.
   - For a one-way door (a data model, a public API, an auth model, a new data store), weigh 2–3
     options in writing. Include the boring ones: extend what exists, use a library the repo
     already has, or don't build it. When the person is available, show them the options with
     your pick.
   - Make reversible choices quickly.
   - Default to the existing patterns, and pick a new one only for a clear reason.
3. **Design.** Define:
   - **Components:** what is new or changed, in which repo or module, and what each is
     responsible for.
   - **Interfaces:** API endpoints (method, path, request, response, errors), events, and
     signatures that cross module boundaries. Agree the contract before the code, so that repos
     which talk to each other share one contract. A change to an existing interface is additive:
     old clients, queued messages and stored data keep working. A breaking change gets a new
     endpoint or version.
   - **Data:** schema changes, written as the migration itself (SQL or the repo's migration code),
     and who owns each piece of data.
     <!-- REVIEW: system-design D1: the eval's migration prompt was lost to a design that showed the actual SQL. -->
     - Change a schema in releases that each work alone: expand (add), migrate (backfill in
       idempotent, resumable batches), then contract (drop the old) in a later release. The code
       shipped with each migration runs on both schemas.
     - Every new query names the index it uses. Every list or batch is bounded or paginated.
   - **Flows:** the main path step by step, and the failure paths: timeouts, retries,
     idempotency, partial failure, and two requests changing the same record at once (use a
     constraint, version check or lock, never check-then-insert alone).
   - **Security:**
     - For each new entry point, data store or external call, name what could go wrong (a
       spoofed caller, tampered input, someone else's data read, flooding, raised rights) and
       the control that stops it. Each control becomes a test.
     - Authorization checks the specific record (owner, tenant), not only sign-in.
     <!-- REVIEW: system-design C1: removed "validate input" and "keep secrets out of logs" (general practice the model already knows). -->
   - **Rollout and rollback:**
     - How the change reaches users: a flag, a percentage, or all at once.
     - How to turn it off without a deploy, or why a revert is enough.
     - When several services change, the deploy order. Every mix of old and new versions must
       work.
     - Which steps can't be undone (dropped data, sent emails, external calls) and how they are
       guarded.
   - **Signals:** the metric, log or alert that would show the new path failing in production,
     and the IDs needed to trace one request.
4. **Check.** Is this the simplest design that meets the requirements? Is anything in it that
   nobody needs? Does every requirement trace to a component? Can each part ship and roll back
   on its own? Revise and check again until the answers are right.

## Rules
- Write each decision with the options you rejected, why, and the cost you accept. A decision
  with only upsides wasn't weighed.
- Add a diagram (mermaid) only when it helps.
- Add no extension points the requirements don't need.
- Every feature flag the design adds has a task, or a note, to remove it once it is fully
  rolled out.
