---
name: node
description: Guides writing, testing and reviewing Node.js and TypeScript code (services, CLIs, libraries and build tooling), covering type design, async and error handling, configuration, security and a severity-ranked review checklist. Applies whenever a change touches .ts/.js/.mts/.cts files, package.json or tsconfig in a Node.js project.
---
# Node.js + TypeScript

Covers: Node.js 22, 24 and 26 LTS (20 is end-of-life), TypeScript 5.x–7.x, ESM and CommonJS packages, npm / pnpm / yarn, Vitest / Jest / `node:test`; NestJS 11–12 in the reference. If the repository's own conventions (its AGENTS.md/CLAUDE.md, lint config, existing code) disagree with this skill, follow the repository.

## Build

### Types
- Keep `strict: true` (add `noUncheckedIndexedAccess` in new projects). Never loosen `tsconfig`, add `@ts-ignore`, or widen to `any` to get green; if suppression is unavoidable use `// @ts-expect-error <reason>` — it fails once the error is gone.
- Type everything from outside the process as `unknown` (request bodies, `JSON.parse`, env, queue messages, third-party responses) and narrow it with a schema (zod, valibot, TypeBox). Derive the type from the schema (`z.infer<typeof Schema>`) so type and runtime check cannot drift.
- Never use `as` to silence an error, and never `x!` without a guard just above — both assert what the compiler could not prove. `as const` and `satisfies` are fine: `satisfies` checks the shape and keeps literal types.
- Model state as a discriminated union, not a bag of optional fields and booleans, so illegal combinations (`status: 'paid'` with no `paidAt`) cannot be built. End every `switch` over a union with an exhaustiveness check:
  ```ts
  function assertNever(x: never): never { throw new Error(`Unhandled: ${JSON.stringify(x)}`); }
  switch (o.status) { case 'draft': return a(o); case 'paid': return b(o); default: return assertNever(o); }
  ```
- Prefer string-literal unions or `as const` objects over `enum` — enums emit runtime code, numeric enums accept any number, and Node's type stripping rejects them (Node 26 removed `--experimental-transform-types`; enable `erasableSyntaxOnly`).
- Brand IDs that are easy to swap (`type UserId = string & { readonly __brand: 'UserId' }`) when a function takes two or more IDs of the same primitive type.
- Give exported functions explicit return types; type parameters `readonly` when the function must not mutate them.
- TypeScript 6+: never add options deprecated in 6.0 and removed in 7.0 (`moduleResolution: node`/`node10`, `baseUrl`, `target: es5`, `outFile`, `esModuleInterop: false`, `downlevelIteration`); `ignoreDeprecations: "6.0"` is a bridge, not a fix. `types` now defaults to `[]`, so list `"node"` explicitly.
- Use `import type` / `export type` for type-only symbols (`verbatimModuleSyntax`) — otherwise single-file transpilers (esbuild, SWC, tsx) may keep or break the import. Exception: classes injected through decorator metadata (see the NestJS reference).

### Modules and runtime
- Follow the package's `"type"` field. ESM never calls `require()` (use `import`, or `createRequire`). CJS may `require()` an ESM-only package directly on Node 22.12+ when its graph has no top-level `await` (else `ERR_REQUIRE_ASYNC_MODULE`) — no dynamic-`import()` workaround.
- Relative imports carry an extension — Node does not guess. With tsc emit and `module: "nodenext"`, write `./user.js` for `user.ts`; when Node runs `.ts` directly, write `./user.ts` with `rewriteRelativeImportExtensions`.
- In ESM use `import.meta.dirname` / `import.meta.filename`, not `__dirname`.
- Prefer built-ins over new dependencies: `fetch`, `AbortSignal.timeout`, `crypto.randomUUID`, `structuredClone`, `util.parseArgs`, `--env-file`, `node:test`. Import core modules with the `node:` prefix.
- Set `engines.node`, commit the lockfile, and install in CI with `npm ci` (or `pnpm install --frozen-lockfile`). Type packages (`@types/*`) go in `devDependencies`.

### Dependencies and publishing
- Keep dependency install scripts off: npm 12+ runs none unless the package is in `package.json` `allowScripts` (`npm approve-scripts`); pnpm runs only `allowBuilds`; on npm ≤11 or yarn set `ignore-scripts=true` in `.npmrc`. Never `dangerouslyAllowAllBuilds` — the 2025–2026 npm worms ran through install hooks.
- Set a release cooldown unless the repo opts out: `min-release-age=1` (days) in `.npmrc`, pnpm `minimumReleaseAge` (minutes), yarn `npmMinimalAgeGate`. Exempt a package (`min-release-age-exclude`) only with a comment saying why — compromised versions are usually pulled within a day.
- Resolve every dependency from the registry: no git, GitHub-shorthand or https-tarball specs (npm 12 sets `allow-git` and `allow-remote` to `none`).
- Publish libraries only from CI through npm trusted publishing (OIDC) with provenance; never store a long-lived npm token in CI secrets or `.npmrc`. Provenance proves where a tarball was built, not that it is safe.

### Async and errors
- Every promise is awaited, returned, or explicitly handled (`void job().catch(logError)`). Never `array.forEach(async …)` — it does not wait and loses rejections; use `for…of` for sequential work, `Promise.all` for independent work.
- Bound concurrency over unbounded input (`p-limit`, batching) — `Promise.all(items.map(save))` on 10k items exhausts connection pools and rate limits. Use `Promise.allSettled` only when you handle the rejected entries.
- Throw `Error` instances (or subclasses with a stable `code`), never strings or plain objects. When wrapping, pass `{ cause: err }` so the original stack survives.
- `catch (err)` is `unknown`: narrow before reading `.message`. Never leave a `catch` empty or log-and-continue as if it succeeded; handle, rethrow, or translate — and log once at the boundary, not at every layer.
- Put a timeout on every outbound call: `fetch(url, { signal: AbortSignal.timeout(5_000) })` — Node's `fetch` has no overall request timeout. Same for DB and queue clients.
- Wrap `JSON.parse` of external data in try/catch (or a safe-parse helper), then validate the result.
- Never block the event loop on a request path: no `*Sync` fs/crypto/zlib calls (`readFileSync`, `pbkdf2Sync`, `scryptSync`) and no CPU-heavy loops over unbounded input; move CPU work to `worker_threads` or a job queue. `*Sync` at startup is fine.
- Use `pipeline` from `node:stream/promises`, not `.pipe()` — `.pipe()` neither forwards errors nor destroys the other streams on failure.
- Let the process crash on `uncaughtException` / `unhandledRejection` (log, exit non-zero); never install a handler that swallows them. Handle `SIGTERM`: stop accepting work, drain in-flight requests, close pools, then exit.

### Config and secrets
- Parse `process.env` once at startup into a typed, validated, frozen config object and exit on missing or malformed values; never read `process.env` inside business code — a missing variable then surfaces as a bug on the first request instead of at boot.
- Never commit secrets or `.env` files; commit `.env.example` with placeholders. Configure the logger to redact tokens, passwords and `authorization`/`cookie` headers.

### Security
- Validate every external input at the boundary with a schema that rejects or strips unknown keys.
- SQL: parameters or tagged-template builders only; never interpolate into raw SQL (`$queryRawUnsafe`, `knex.raw` / `sequelize.query` with `${}` or `+`). NoSQL: reject object-valued input where a string is expected (`{ "$gt": "" }`).
- Shell: `execFile` / `spawn` with an argument array and no `shell: true`; never `exec` a string built from input.
- Paths from input: `const p = path.resolve(root, input)` (with `root` already absolute) then require `p.startsWith(root + path.sep)` before any `fs` call.
- Never `eval`, `new Function`, or `vm` (not a sandbox) on untrusted strings; never pass unescaped input to `new RegExp`, and avoid nested quantifiers in regexes that run on input (ReDoS).
- Never deep-merge or `Object.assign` untrusted objects into existing ones (prototype pollution); use `Map` or `Object.create(null)` for user-keyed dictionaries.
- Parse URLs with `new URL()` / `URL.parse()`, never `url.parse()` — its non-standard parsing allows hostname spoofing (DEP0169; warns in app code since Node 24).
- Tokens and IDs from `crypto.randomBytes` / `randomUUID`, never `Math.random`. Compare secrets and HMACs with `crypto.timingSafeEqual`. Hash passwords with argon2, bcrypt or scrypt.
- HTTP servers: body-size limit, CORS allowlist (never `*` with credentials), security headers (helmet or equivalent), rate limits on auth endpoints.

### Structure
- Keep handlers thin: validate input, call a service, map the result to a response type. Never return ORM entities or raw rows — they leak password hashes and internal columns.
- No module-level mutable state (caches, counters, stateful singletons) unless deliberate and commented — it leaks across requests and tests and diverges across instances.
- Pass dependencies in (constructor or factory parameters) instead of importing stateful singletons, so tests substitute them without module mocking.
- Log through a structured logger (pino or the framework's) with a request/correlation id; no `console.log` in server code.
- Express 4 never forwards a rejected `async` handler to error middleware — wrap it or use Express 5, which does. Express 5 paths: named wildcards (`/*splat`, `/{*splat}` to include `/`), braces instead of `?`; `req.query` is read-only and the default `simple` parser drops nested `a[b]=c`.

### Client bundles (Vite and similar)
- Anything in `VITE_*` / `NEXT_PUBLIC_*` is inlined into shipped JavaScript: public values only. Never `loadEnv(mode, root, '')` or `envPrefix: ''` — both expose every variable.
- `vite build`, esbuild, SWC and tsx transpile without type-checking: CI must also run `tsc --noEmit`.
- Keep `build.sourcemap` off in production unless maps go only to the error tracker.

## Test
- Use the repo's runner. With none: Vitest for application code (native ESM and TS), `node:test` for small libraries without a build step. Jest needs a transform (ts-jest or SWC) and extra ESM setup.
- Test behaviour through the public interface — returned values, thrown errors, calls at the system boundary — not private helpers. Name tests after the behaviour: `it('rejects an expired token with 401')`.
- Cover error and validation paths, not only the happy path: invalid input, upstream failure and timeout, empty and boundary values. Every bug fix gets a regression test that fails without the fix.
- Always `await` async assertions: `await expect(p).rejects.toThrow(NotFound)` — without `await` the test ends before the promise settles and passes vacuously.
- Mock only boundaries you do not own: HTTP with msw, nock or undici `MockAgent`; time with `vi.useFakeTimers()` / `vi.setSystemTime()`. Prefer injecting a fake over `vi.mock` / `jest.mock` of your own modules; never mock the unit under test.
- Reset mocks between tests; no test may depend on order or leftover state. In Vitest set `restoreMocks: true` and `clearMocks: true` (or `mockReset: true`) — `restoreAllMocks` only restores `vi.spyOn` originals and keeps `vi.fn()` call history.
- Never sleep (`setTimeout`) to wait for async work — use fake timers or await the actual event.
- Run data-access tests against a real database (Testcontainers or a disposable schema), resetting state per test — mocked query builders miss SQL and migration errors.
- Drive HTTP tests through the real app with its validation and error middleware (supertest, Fastify `inject`), and close the app and pools in `afterAll`.
- Never make a snapshot the only assertion on a large object; assert the fields that matter.

## Review
Severity: **Critical** blocks merge (security, data loss). **High** is fixed before merge unless explicitly accepted. **Medium** is fixed or justified. React/Next.js component checks are out of scope here — review them with React-specific rules.

### Critical — Security
- `eval` / `new Function` / `vm` reachable by user-controlled input.
- XSS: unsanitised input into `innerHTML`, `dangerouslySetInnerHTML`, `document.write`, or server-rendered HTML without escaping.
- SQL/NoSQL injection: concatenation or interpolation into queries; object-valued input reaching a NoSQL filter.
- Path traversal: user input reaching `fs.*` / `path.join` without `path.resolve` plus a root-prefix check.
- Hardcoded secrets (keys, tokens, passwords, connection strings) in source, tests, or `VITE_*` / `NEXT_PUBLIC_*` variables.
- Prototype pollution: untrusted objects merged without schema validation or a null-prototype target.
- `child_process` with user input: `exec` or `shell: true` with interpolated strings, or arguments not validated against an allowlist.
- New endpoint without authentication, or authorization that checks role but not ownership of the resource.

### Critical — Supply chain
- New or changed `allowScripts`/`allowBuilds` entry, `ignore-scripts=false`, or a new lifecycle script in `package.json`, without a stated reason.
- Lockfile entry resolving from git, a GitHub shorthand or an https tarball; a lockfile change with no matching `package.json` change that the task didn't ask for.
- Added or changed `.claude/settings.json`, `.vscode/tasks.json`, git hooks or CI workflow files the task did not ask for — worms plant these for persistence.
- Publishing workflow that uses a stored npm token instead of trusted publishing.

### High — Type safety
- `any` without a justifying comment — use `unknown` and narrow, or a precise type.
- `value!` with no preceding guard.
- `as` casts that bypass checks (`as unknown as T`, casting to unrelated types) — fix the type instead.
- `tsconfig.json` changes that weaken strictness, or new `@ts-ignore`; call these out explicitly.
- Optional-field bags or boolean flags where a discriminated union is needed; `switch` over a union with no exhaustiveness check.
- tsconfig adding an option deprecated in TypeScript 6.0, or `ignoreDeprecations` with no migration note.

### High — Async correctness
- Floating promise (not awaited, returned or `.catch()`-ed) anywhere, including event handlers and constructors; `array.forEach(async …)`.
- Async Express 4 handler with no wrapper forwarding rejections to `next`.
- Sequential `await` in a loop for independent work — `Promise.all` instead; unbounded `Promise.all` over large input — bound it.
- Outbound HTTP/DB call with no timeout or abort signal.

### High — Error handling
- Swallowed errors: empty `catch`, or catch that logs and continues as if it succeeded.
- `JSON.parse` of external data without try/catch.
- Throwing non-`Error` values (`throw 'msg'`, `throw { code }`); rewrapping without `cause`.
- Internal error messages or stack traces returned to clients.

### High — Node.js runtime
- Synchronous fs/crypto/zlib in request handlers or hot paths — it blocks the event loop.
- External data (body, query, headers, messages, files) used without schema validation at the boundary.
- `process.env` read without startup validation or fallback.
- `require()` in ESM; a dynamic-`import()` or bundler workaround for an ESM-only package that Node 22.12+ can `require()` directly.
- `.pipe()` without error handling; streams not destroyed on failure; `url.parse()` on any input.
- Module-level mutable shared state; callback-style APIs mixed with `async/await` (use `node:fs/promises`, `util.promisify`).

### Medium — Performance
- N+1: database or API calls inside loops — batch, or `Promise.all` with a bound.
- Large files or result sets loaded fully into memory where streaming or pagination is needed.

### Medium — Best practices
- `console.log` left in production code — use the structured logger.
- Magic numbers and strings — named constants or literal-union types; `enum` where a union would do.
- Exported functions without explicit return types.
- New dependency for something trivial or already built in; `@types/*` or build tools in `dependencies`.

## Verify
Prefer the repo's own `package.json` scripts (`typecheck`, `lint`, `test`, `build`) and its package manager (the lockfile tells you: npm, pnpm, yarn or bun). Fallbacks:
```bash
npm run typecheck --if-present       # else: npx tsc --noEmit -p <tsconfig owning the changed files>
npx eslint .                         # lint
npx prettier --check .               # format
npx vitest run                       # or: npx jest --ci / node --test
npm run build --if-present
npm audit --omit=dev                 # or the pnpm/yarn/bun equivalent
```
- Type-check every tsconfig that owns changed files (`tsc -b` in project-reference monorepos). Transpiling runners (Vitest, tsx, SWC-Jest) do not type-check, so a green test run is not a green build.

## References
- `references/nestjs.md` — read when the project uses NestJS (`@nestjs/*` in package.json, `@Module` / `@Controller` decorators): modules and DI, DTO validation, guards, exception filters, config, persistence, testing, and NestJS-specific review items.
