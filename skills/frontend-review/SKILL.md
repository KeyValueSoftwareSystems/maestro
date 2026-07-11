---
name: frontend-review
description: Review the frontend implementation AFTER it is built — UI-state completeness, accessibility, security, resilience, forms, performance, responsive/i18n, test gaps. Read-only; writes a review artifact. Front door for /frontend-review.
allowed-tools: Read, Grep, Glob, Bash, Task, Write
tags: [sdlc, review, frontend]
---

# frontend-review

Review the frontend implementation (diff/branch) against the contract and LLD. Read-only —
never edit code.

## Steps
1. **Scope the diff** — changed pages/components, new hooks, and the routes affected.
2. **Check consumption** against the contract (shapes, error codes) and the required UI states.
3. **Deep, evidence-backed pass** over every dimension in the checklist below. For a more
   independent read you MAY spawn a fresh read-only sub-agent (via the Task tool) that follows
   this same skill — do this where your harness supports it (e.g. Claude Code). Otherwise
   perform the pass **inline**. Either way: **read-only — never edit code.** You are the
   read-only backstop; nothing is skipped.
4. **Consolidate** by severity; decide `blocking`.
5. **Write** the report and return the verdict.

## What the review must cover (checklist — independent of the external skill)
- **UI-state completeness** — loading, empty, success, validation error, API error,
  permission denied, retry/failed — each reachable and correct.
- **Accessibility (WCAG AA)** — keyboard operable, visible focus, roles/labels, contrast,
  screen-reader semantics, focus management, no traps.
- **Security** — no secrets/tokens in client; XSS-safe rendering/escaping; CSRF-safe
  requests; validated redirects; no PII in logs/analytics.
- **Contract consumption** — calls the API as published; no invented shapes; all documented
  error codes handled.
- **Resilience** — slow/failed/stale APIs handled with retry/backoff + messaging; optimistic
  updates roll back; double-submit guarded.
- **Forms & validation** — mirrors the contract; field-level errors; submit disabled while pending.
- **Performance** — code-split/lazy-load; avoid needless re-renders; bundle size; large-list
  virtualization.
- **Responsive & i18n** — breakpoints; long text/overflow; localizable strings; locale
  formatting; RTL if supported.
- **Test gaps** — component + E2E cover the acceptance criteria and the UI states;
  assertions meaningful.

## Edge cases / smells to watch for
- Only the happy path styled; missing empty/error/permission states.
- `dangerouslySetInnerHTML` / unescaped user content; tokens in localStorage or logs.
- Buttons with no disabled/pending state (double-submit); no rollback on failed optimistic update.
- Non-semantic clickable `div`s; missing labels; focus lost after navigation/modal close.
- Hard-coded copy in a localized app; layout breaking on long text or small screens.
- Large list rendered without virtualization; unbounded re-renders.

## External skill (provision — review method)
If the `requesting-code-review` skill (from the Superpowers pack) is installed, apply its
discipline first; it must not narrow the checklist above. If it is not installed, review
inline per the checklist.

## Findings format (what the review returns — evidence mandatory)
```
summary: <one paragraph verdict + top risks>
findings:
  - severity: blocker | major | minor | suggestion
    area: ui-state | accessibility | security | contract | resilience | forms | performance | responsive-i18n | test-gap
    file: <path:line>
    evidence: <quoted code / the missing state or check>
    recommendation: <smallest safe change>
    safe_for_ai_fix: <true|false>
blocking: <true if any blocker/major remains>
```

## Decide & output
Sort blocker → major → minor → suggestion; `blocking = true` if any blocker/major remains.
Write the report to `.maestro/<slug>/frontend/reviews/summary.md` — this skill owns where
it writes. A blocking result routes back to the frontend
implementer — the engine's visit cap (`max_visits`, typically 3) bounds that loop, not you.

## Output contract
Return `review_path` and `blocking`.

When invoked as a Maestro workflow step, your reply's LAST line must be exactly one JSON
object with these fields — short scalar values only, never file contents.
