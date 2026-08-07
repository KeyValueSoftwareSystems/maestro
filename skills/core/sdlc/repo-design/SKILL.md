---
name: repo-design
description: Author the low-level design (LLD) for a feature IN ONE REPO — read that repo's code to ground the design, then design how the feature slots into it (structure, data/state, the interfaces it exposes and/or consumes, NFRs, tests). Repo-agnostic — works for a backend, frontend, mobile app, or any other repo, whatever it turns out to be. Writes the LLD doc; never edits app code. Front door for /repo-design.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, design, lld]
---

# repo-design — low-level design for one repo

Design how a feature slots into **one specific repo**: read enough of its real code to ground
the design, then write a **buildable LLD for that repo alone**. This is a design artifact, not
code — never edit app code, don't implement, and don't design any other repo. The **cross-repo
contract** is not written here — you describe what this repo exposes and/or consumes; a
separate step reconciles every repo's LLD into the formal contract.

This skill is deliberately repo-agnostic: it does not assume "backend" or "frontend." The repo
you're given could be either, a mobile app, a CLI, a library, an infra/pipeline repo, or
anything else — figure out what it actually is from its own code and map it to the sections
below, marking a section "n/a" when it genuinely doesn't apply rather than forcing content.

## Inputs
Your instructions name the **repo** you own (by name/path), the approved HLD, the feature, and
the artifact path to write. Standalone? ask which repo, or infer it from the current directory,
and write to a path you choose (and tell the user where).

## Steps
1. **Identify what this repo is.** Read its `docs/codebase-map.md` first (umbrella layout:
   `codebase/<repo>/docs/codebase-map.md`) — the standing description of its modules, flows and
   execution modes — plus its `CLAUDE.md`/manifest (`package.json`, `pubspec.yaml`,
   `pyproject.toml`, a Terraform/CI config, whatever exists). From that, decide its shape: does
   it serve requests, render UI, run on a device, ship as a library, define infrastructure? That
   shape determines which sections below carry real content.
2. **Ground in the code, cheaply.** Read the actual source only where the feature needs context
   the map doesn't cover — the specific flow you're extending and any execution mode it touches.
   Cite `file:line` for every constraint you rely on; don't guess. An approach that fits the
   happy path but breaks an existing mode (async, batch, offline, multi-tenant…) is a wrong LLD.
3. **Design the structural change** — the modules/components/objects and their responsibilities,
   and the sequence for each critical path (happy + main error paths); where new code slots in.
4. **Data & state** (if this repo owns any) — entities, storage/persistence, migration or
   versioning plan with rollback. Mark "n/a — this repo holds no persistent state" if true.
5. **Interfaces** — for EACH interface this repo touches, say which direction: what it
   **exposes** (an API/event/screen/CLI command others call into) and what it **consumes** (an
   API/event/SDK it calls out to). A repo can do both. Be concrete: method/path or
   event/topic/screen name, request/response shape, error handling, auth. This is this repo's
   *side* of any contract — reconciliation with other repos happens in a later step.
6. **Non-functional requirements**, scaled to what's real here: security & privacy (authz,
   secrets, PII), performance, reliability (retries, idempotency, partial failure), and
   observability. Skip a sub-area explicitly (state why) rather than padding it.
7. **Edge cases** the design must define, not leave to the implementer (empty/oversized inputs,
   concurrent updates, partial failure, auth denial, rate limits — whichever apply to this
   repo's shape).
8. **Test plan** — coverage appropriate to this repo's shape (unit/integration/component/E2E).
9. **Write** the LLD; flag anything that constrains or must be reconciled with other repos'
   designs (their existence, not their content, is all you may assume).

## What the LLD must cover (write all; mark a section "n/a" with a one-line reason if it
genuinely doesn't apply to this repo's shape)
Context & constraints (grounded in the code, cited) · structural/component design · data &
state · interfaces exposed and/or consumed · security & privacy · performance · reliability ·
observability · edge cases · test plan · rollout/backout note for this repo alone.

## Output contract
Write your LLD to the given artifact path, with the sections above, each constraint citing
`file:line`. Return `lld_path` and `contract_notes` — a short summary of the
**decisions/constraints that shape reconciliation with other repos** (e.g. "exposes
`GET /favorites` with cursor pagination"; "consumes the backend's existing auth token, no
change needed"). The interfaces section feeds the cross-repo contract step.

## Definition of done
Every applicable section present and concrete enough to reconcile against other repos'
designs; "n/a" sections justified in one line, not silently dropped; edge cases specified (not
"TBD"); breaking changes flagged. Do not implement — this is a design artifact only.
