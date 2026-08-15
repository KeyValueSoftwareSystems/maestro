---
name: repo-design
description: Produce a concise, buildable low-level design (LLD) for one repository. Ground it in that repo's code, show the implementation seam, responsibilities, critical flows, interfaces, state, and verification without repeating the HLD or padding irrelevant sections. Writes only the LLD. Front door for /repo-design.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, design, lld]
---

# repo-design — low-level design for one repo

Write the implementation map for one repository. A developer or implementation agent should quickly
see where the feature fits, what changes, how the important flows behave, which order to build them
in, and how to verify the result. The LLD must preserve enough decisions for implementation to
continue without another architecture pass. Do not implement, edit application code, redesign
another repo, or repeat the HLD's product and architecture narrative.

This skill is repo-agnostic. Determine whether the repo is a backend, UI, mobile app, library, CLI,
infrastructure project, pipeline, or something else from its own evidence. Describe only this repo's
side of cross-repo interfaces; the later contract step reconciles all sides.

## Inputs and grounding

Your instructions name the repo, approved HLD, feature, and artifact path. Read the HLD, then read the
repo's `docs/codebase-map.md`, project guidance, and relevant manifest. Inspect the real source around
the flow being changed, its tests, and every execution mode the feature touches.

Use code evidence to confirm design constraints rather than to decorate the document. Collect the
small set of decision-driving references in a compact `claim | source` table or cite them beside the
relevant decision. Do not attach `file:line` to every sentence.

## Process

1. Identify the existing design seam: the interface through which current callers, users, jobs, or
   tests reach the behavior being changed.
2. Map the approved HLD direction onto this repo's existing modules and conventions. Prefer extending
   a proven seam over adding a parallel architecture.
3. Define responsibilities and dependencies for each changed or new module. Keep interfaces small
   and hide implementation detail behind them.
4. Describe the critical success flow and only the failure, retry, concurrency, offline, or recovery
   flows that change control, state, or externally visible behavior.
5. Specify interfaces and state precisely where they exist: direction, names, shapes, validation,
   errors, authorization, ownership, persistence, migration, and compatibility.
6. Include security, privacy, performance, reliability, observability, rollout, and backout only when
   they constrain this repo's implementation or operation.
7. Order the work into dependency-aware, independently verifiable increments. Put foundational
   contract or state changes before their consumers and identify safe checkpoints.
8. Map acceptance behavior to tests at the highest stable seam available.
9. Edit once for the implementer: remove repeated HLD context, generic guidance, obvious framework
   behavior, and any section that contains no useful decision.

## LLD shape

Use these core sections in this order:

1. **Change summary** — a short list of this repo's responsibilities, exposed or consumed behavior,
   and the implementation boundary.
2. **Existing design seam** — the current modules, conventions, and constraints the change extends,
   with compact code evidence.
3. **Proposed changes** — preferably an `area | change | responsibility` table followed by rationale
   only where needed.
4. **Critical flows** — numbered flows or sequence diagrams for ordering that matters. Cover the main
   success path and material failure paths; do not enumerate trivial variations.
5. **Implementation sequence** — dependency-ordered increments with a concrete result and verification
   checkpoint for each. This is an order of work, not a file-by-file task dump.
6. **Verification** — acceptance behavior mapped to unit, integration, component, or end-to-end tests,
   including the existing test seam or prior art to follow.

Add the following sections only when they carry real design information:

- **Interfaces and state** — contracts exposed or consumed, data ownership, persistence, migration,
  versioning, compatibility, validation, authorization, and error behavior.
- **Operational behavior** — relevant security/privacy, performance, reliability, observability,
  rollout, or backout decisions.
- **Open implementation decisions** — unresolved choices that an implementer cannot safely make
  alone.

Omit irrelevant optional sections completely. Do not add empty headings, `n/a` entries, or generic
claims that the implementation will be secure, scalable, observable, or well tested.

## Writing contract

- Write for the developer who will implement this repo's part of the feature.
- Lead each section with the answer. Use active voice, short sentences, specific names, and one idea
  per paragraph.
- Prefer tables for module mappings, interfaces, state transitions, and test coverage. Use prose to
  explain non-obvious reasoning and diagrams only when order or topology is otherwise hard to follow.
- Include enough interface and state detail to build and reconcile the design, but avoid code listings
  and speculative file inventories.
- Make ownership, dependency direction, invariants, and externally visible failure behavior explicit.
  Do not make the implementation agent infer decisions that affect correctness.
- Aim for 900–1,800 words for a normal repo. Genuine implementation complexity can justify more;
  repeated context and template padding cannot.

## Revision mode

Treat review feedback as rewrite instructions. Update the design in place so it reads as one current
implementation plan. Do not include reviewer suggestions, revision history, "previous design"
narration, or a list of changes made during review.

## Output contract

Write the LLD at the requested artifact path. Return `lld_path` and concise `contract_notes` containing
only the decisions or constraints that another repo must reconcile, such as an exposed route, event,
token expectation, or compatibility requirement. Do not repeat the LLD summary in `contract_notes`.

## Definition of done

A developer or implementation agent can identify the seam, proposed changes, dependency order, and
verification checkpoints without rereading the HLD or repeating broad codebase discovery. Every
material constraint is grounded; critical flows, interfaces, state behavior, invariants, failure
behavior, and tests are specific enough to implement when applicable; breaking changes are explicit;
and no irrelevant or revision-process content remains. Do not implement the feature.
