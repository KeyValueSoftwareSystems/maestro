# Feature-Slug Document Archival — Design

**Date:** 2026-07-03
**Status:** Approved (design) — pending implementation plan

## Problem

Every feature run through the KeyValue AI-SDLC pipeline produces a scattered set of
per-feature artifacts keyed by `feature_slug`:

- `docs/technical/<slug>/hld.md`, `docs/technical/<slug>/lld/{backend,frontend}.md`
- `contracts/<slug>/openapi.yaml`
- `docs/functional/<slug>/acceptance-criteria.md`
- `.sdlc/<slug>/` (tasks, verify reports, reviews, review-pack)

As features accumulate, three problems emerge (in priority order):

1. **Clutter / discoverability** — `docs/` fills with dozens of per-feature folders; the
   *current* state of any area of the system is hard to find.
2. **Stale knowledge** — feature docs describe how something was built *at the time*;
   months later they are out of date and misleading. There is no "living current-truth" view.
3. **Repo hygiene** (minor) — volume of per-feature docs bloats the working tree.

Provenance/audit is **not** a priority: git history already preserves every removed folder,
so files do not need to be kept on disk solely for the record.

## Goal

A deliberate, human-gated archival action that distills each finished feature's durable
knowledge into **living, current-truth domain documents**, and removes the retired
per-feature working docs from the tree — keeping the active working set clean while
preserving recoverability through git history.

## Decisions

- **Extract, don't keep.** Distill durable facts into living domain docs; do not cold-store
  whole feature folders. (Cold storage would leave scannable files — see Constraints.)
- **Living-doc merge, not append.** Archiving reconciles new facts into existing domain docs
  as current truth (merge / supersede + changelog), rather than appending dated snapshots.
  This is the only approach that delivers the "current-truth" goal.
- **Two-dimensional taxonomy:** `docs/<lens>/<domain>/`, where `<lens>` ∈
  {`business`, `technical`, `architecture`} and `<domain>` is a bounded business area
  (`auth`, `search`, `payments`, …).
- **Registry defined here, domain confirmed per-feature.** A bootstrapped
  `docs/domains.yaml` lists valid domains. At archive time the skill infers a domain and a
  human confirms it, picks an existing one, or creates a new one (which extends the registry).
- **Form factor:** a new `/archive` skill (the reusable unit) that `main.yaml` calls as its
  closing step — matching the repo's "skill is the unit, workflow calls the slot" pattern.

## Constraints

- **Retired feature folders must not leak into later brainstorming.** When a *new* feature is
  brainstormed/planned, the plan/brainstorm skill scans `docs/` and could re-read old feature
  docs as if they were live, anchoring the new design on obsolete detail. To prevent this,
  retired per-feature folders are **removed from the working tree entirely** (recoverable via
  git), so there is nothing to scan. Living domain docs remain on disk and may be read; only
  the raw retired feature folders are excluded.

## On-disk structure

Living domain docs (durable output) — three canonical files per domain:

```
docs/
  business/<domain>/capabilities.md      # what this domain does for users + business rules
  technical/<domain>/design.md           # how it's built: data model, components, APIs, security
  architecture/<domain>/architecture.md  # boundaries, cross-domain deps, key decisions (ADR-style)
```

Domain registry (source of truth for valid domains):

```
docs/domains.yaml          # e.g.  domains: [auth, search, payments, notifications]
```

**Namespace note:** feature artifacts sit at `docs/technical/<slug>/hld.md` and
`docs/functional/<slug>/`; living domain docs share the `docs/technical/` (and
`docs/business/`, `docs/architecture/`) trees keyed by `<domain>` instead of `<slug>`. Because
feature folders are removed after archival the overlap is transient, and living docs use fixed
filenames (`design.md`, `capabilities.md`, `architecture.md`) that never collide with feature
filenames (`hld.md`, `lld/…`). `docs/functional/` stays feature-scoped.

## Extraction mapping (source → lens)

| Living doc | Pulls durable knowledge from | Distills to |
|---|---|---|
| `business/<domain>/capabilities.md` | HLD (goals/scope), `docs/functional/<slug>/acceptance-criteria.md` | User-facing capabilities, business rules, key behaviors (drops feature-specific framing) |
| `technical/<domain>/design.md` | `docs/technical/<slug>/lld/{backend,frontend}.md`, `contracts/<slug>/openapi.yaml` | Data model, core components, API/event surface, error handling, security & observability decisions |
| `architecture/<domain>/architecture.md` | HLD (architectural direction), architecture-review artifact in `.sdlc/<slug>/` if present | Bounded-context boundaries, cross-domain dependencies, significant decisions (ADR-style) |

**Not extracted** (ephemeral process residue, left to git history): `.sdlc/<slug>/` task
lists, verify reports, review packs, fix-loop output — these describe *how the work was done*,
not *how the system works*.

**Contract handling:** `contracts/<slug>/openapi.yaml` is already durable and machine-readable.
It is **referenced** from `technical/<domain>/design.md` and left authoritative (moved to a
domain-keyed `contracts/<domain>/` rather than prose-summarized), so fidelity is not lost.

**Uncertain content** the skill cannot confidently place is surfaced in the human-review step,
never silently dropped.

## The `/archive` skill flow

Runs against a finished `feature_slug`:

1. **Locate & validate** — resolve the feature's artifact paths from `skills.config.yaml`;
   confirm expected docs exist (HLD, LLDs, acceptance, contract). Missing-but-expected
   artifacts are reported, not fatal.
2. **Propose domain** — read the feature docs, infer the best-fit domain, present the proposal:
   *"This feature looks like `search`. Confirm / pick from [auth, payments, …] / enter new."*
   New domain → append to `docs/domains.yaml` + scaffold the three empty lens files.
3. **Distill per lens** — produce extracted current-truth content per the mapping above.
4. **Merge, don't overwrite** — for each lens doc: create it if absent; otherwise reconcile —
   merge new facts, replace superseded ones, append a changelog line
   (`YYYY-MM-DD · <slug> · <one-line what changed>`).
5. **Human-review the diff** — present the full diff of all three lens docs (+ any registry
   change) for approval. Guardrail against lossy/garbled merges. Changes land only on approval;
   the human can edit or reject.
6. **Retire the feature folder** — on approval, remove per-feature working docs
   (`docs/technical/<slug>/`, `docs/functional/<slug>/`, `.sdlc/<slug>/`) from the working
   tree. Git history retains them; the changelog line records the pre-removal commit ref for
   recovery. Contract handled per mapping (referenced/moved, not deleted).
7. **Commit** — one commit: living docs updated + feature folder retired + registry updated,
   message `archive(<domain>): <slug>`.

## Guardrails

- **Two human gates** — domain assignment, and the merge diff — both approved before anything
  lands.
- **Nothing silently dropped** — unplaceable content is surfaced in review.
- **Recoverable** — changelog records the pre-removal commit ref; git history holds the raw
  folders.
- **Idempotent** — re-running on an already-archived slug is a no-op (empty diff).
- **Contract preserved** — OpenAPI referenced, not prose-summarized.

## Integration

- New skill `skills/archive/SKILL.md` (front door `/archive`).
- New slot in `skills.config.yaml` (e.g. under `shared:` or a new `archive:` key), plus
  registry/living-doc paths added to the `artifacts:` block:
  - `registry: docs/domains.yaml`
  - `living: docs/<lens>/<domain>/`
- `main.yaml` gains a closing step after `human-review-pack` that calls `/archive` with a human
  confirm gate (domain proposal + merge diff).

## Testing (POC-appropriate, matching repo conventions)

- **Fresh-domain case:** fixture feature folder (sample HLD/LLD/contract/acceptance) → run
  `/archive` → assert three lens docs created with expected sections, registry updated, feature
  folder gone from working tree, changelog line present.
- **Idempotency case:** second run on the same fixture → assert no-op (empty diff).
- **Merge case:** pre-existing domain doc + new feature → assert facts merged and changelog
  appended (not overwritten).

## Out of scope

- Automatic archival at ship time without a human gate.
- Cold-storage / on-disk archive of raw feature folders.
- Retroactive migration of already-shipped feature folders (can be a follow-up batch run of
  `/archive`).
