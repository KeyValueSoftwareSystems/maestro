---
name: verify
description: Run the project's deterministic checks and produce an evidence-backed proof report plus a machine-readable proof marker. Never modifies code (writes only its proof artifacts). Use after any implementation to prove it works. Front door for /verify.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, qa, verify]
---

# verify

Run the relevant deterministic checks from `CLAUDE.md` and produce proof. **Deterministic
checks are the proof — the model's claim is not.** Never modify code (you write only the
proof artifacts below).

## Steps
1. **Discover** the project's real commands (from `CLAUDE.md`/scripts); don't assume.
2. **Bring up the env** if integration/E2E need it (`stack up` → seed → ready_check);
   ensure teardown afterward.
3. **Run each check**, capturing the exact command, exit code, and a short output tail.
4. **Stop at the first hard failure** for the fast path, but still record what ran.
5. **Write the report + marker** (below). Set overall `status` = pass only if all required
   checks passed.
6. If anything failed, hand off to `/fix` — do not fix here.

## Checks to run
**Backend proof:** lint · typecheck · unit tests · integration tests · migration check
(if applicable) · API contract (provider-side) validation · coverage vs the
coverage bar: **80% on changed code**.
**Frontend proof:** lint · typecheck · unit/component tests · build ·
Storybook/component check (if available) · Playwright E2E · accessibility basics.

## Report (stdout)
- exact commands run · pass/fail per command · the exact failed command (if any) · error
  summary + suspected root cause · next recommended action.

## Proof artifacts (this is what makes "done" checkable, not just claimed)
Also WRITE (under the feature work dir `.maestro/<slug>/`, `<slug>` = `feature_slug`):
- `.maestro/<slug>/<stack>/verify.md` — the human-readable report above.
- `.maestro/<slug>/<stack>/last-verify.json` — the marker, e.g.
  `{"status":"pass|fail","date":"<YYYY-MM-DD>","stack":"backend|frontend","checks":[{"cmd":"…","result":"pass|fail"}]}`.

Nothing auto-runs this for you — it's on you (or `/review-pack`) to check the marker exists
and is fresh before treating an implementation as done. **The proof is produced by this
command**, not assumed.

## Edge cases / pitfalls
- **Flaky failure** vs real: re-run once; if it passes intermittently, record it as flaky
  and surface it — do not mark green and move on.
- **Env not up / port in use** — an environment error is not a passing test; report it distinctly.
- **Partial pass** — some suites green, one red → overall `status:"fail"`.
- **Skipped/`todo` tests** or disabled checks — call them out; they are not proof.
- **Coverage below threshold** — a fail even if all tests pass.
- **No tests found** for changed code — a gap; report it rather than reporting success.

## Definition of done
Never accept "everything works". Overall `status` reflects the weakest required check; the
marker and report are written; on failure the next action points at `/fix`.

## Output contract
Return `status` (`pass`|`fail`), `report_path` (the verify.md written), and `failed_cmd`
(the exact first failing command, empty string on pass).

When invoked as a Maestro workflow step, your reply's LAST line must be exactly one JSON
object with these fields — short scalar values only, never file contents.
