---
name: react
description: Rules for writing, testing and reviewing React code (components, hooks, forms, Server Components) in TypeScript. Use when creating or changing .tsx/.jsx files, writing React Testing Library tests, or reviewing a React diff, including Next.js and React Native projects.
---

# React

Covers: React 18 and 19 through 19.3 (19-only APIs are marked), TypeScript, React DOM in client-rendered and SSR apps; tests with React Testing Library, Vitest or Jest, and MSW 2–3. Next.js App Router (15–16) and React Native / Expo are in the references. If the repository's own conventions (its AGENTS.md/CLAUDE.md, lint config, existing code) disagree with this skill, follow the repository.

## Build

### State and effects
- Derive values during render; never copy props or state into another state through `useEffect` — it costs an extra render and drifts out of sync.
- Never load application data with `useEffect` + `fetch`; use the framework's loader / Server Component or a server-cache library (TanStack Query, SWR) — raw effects race and don't dedupe, cache or retry. If an effect must fetch, abort or ignore the stale result in its cleanup.
- Every effect that subscribes, adds a listener, starts a timer or opens a connection returns a cleanup.
- Put logic caused by a user action in the event handler, never in an effect that watches state the handler just set.
- Use the functional updater (`setX(prev => …)`) when the next state depends on the previous; never mutate state and set the same reference.
- Reset a component's internal state on identity change with `key={id}` at the call site, not with an effect watching the prop.
- Dependency arrays list every reactive value, as primitives (`[user.id]`, not `[{ id }]`). Never disable `react-hooks/exhaustive-deps` without a comment saying why. Functions from `useEffectEvent` (19.2) are not deps.
- Pick state location in this order: local `useState` → lift to the nearest common ancestor → Context for low-frequency tree-wide values (theme, auth, locale) → external store (Zustand, Jotai, Redux Toolkit) for high-frequency shared state → server-cache library for anything that comes from a server. Never copy server data into a client store — two sources of truth go stale.
- Split Context by concern so a fast-changing value doesn't re-render unrelated consumers. Read stores through the narrowest selector (`s => s.cart.length > 0`, not `s => s.cart`); read values used only in callbacks at call time (`store.getState()`), not via subscription.
- Hand-written external stores are read with `useSyncExternalStore` — anything else tears under concurrent rendering.

### Components
- Never declare a component inside another component's body — it is a new type each render, so its subtree remounts and loses state.
- Keys are stable ids from the data; never the array index (or `Math.random()`) for lists that reorder, insert or delete.
- Never `{count && <X />}` with a number — `0` renders as text; write `count > 0 ? <X /> : null`.
- Function components only in new code; error boundaries are the exception (prefer `react-error-boundary`).
- Custom hooks are named `use*` (the lint rules depend on it); extract one only when the same hook sequence appears in 2+ components.
- Hoist constant non-primitive defaults to module scope (`const EMPTY: Item[] = []`) instead of `items ?? []` inline when the receiver is memoized.
- React 19: take `ref` as a normal prop; keep `forwardRef` only while the package must still support React 18.

### Memoization and responsiveness
- Don't memoize by default. Add `memo`/`useMemo`/`useCallback` only when a profile shows the cost, or the value is a prop of a memoized child or a dep of another hook.
- Under React Compiler add no memo for render cost; use `useMemo`/`useCallback` only to keep an effect dependency stable. Never strip existing memoization without tests — removing it changes the compiler's output.
- `useMemo` around cheap primitive math is pure overhead; reserve it for expensive work or for identity something depends on.
- For expensive non-urgent updates (filtering a large list on each keystroke) use `startTransition` or `useDeferredValue`, not a hand-rolled render debounce.
- Virtualize lists of more than ~50 non-trivial rows (`@tanstack/react-virtual`, `react-window`).

### Async, Suspense, errors
- Place `<Suspense>` boundaries close to the data that suspends, not only at the route root; size fallbacks like the final content to avoid layout shift.
- Wrap suspending trees in an error boundary. Boundaries don't catch errors from event handlers or async code — catch those and put them in state.
- React 19 `use(promise)`: never create the promise during a Client Component's render — a new promise each render suspends forever. Create it in a Server Component, a loader, or a cache.
- Start independent requests together (`Promise.all`, or create promises early and await late); check cheap synchronous conditions before the first `await`.

### Forms
- React 19: `<form action={fn}>` with `useActionState` (and `useFormStatus` in the submit button) — it handles `preventDefault`, pending state and reset; use `useOptimistic` for optimistic rows. React 18: `onSubmit` with `e.preventDefault()`.
- Every input has a `name` (so `FormData` sees it) and an associated label.
- Multi-step forms, field arrays or cross-field validation use React Hook Form or TanStack Form with a schema (zod, valibot) — not hand-rolled state.

### Security and accessibility
- Never `dangerouslySetInnerHTML` with non-constant HTML unless DOMPurify (or an equivalent allowlist sanitizer) runs at the same call site.
- User-supplied `href`/`src` pass a scheme allowlist (`https:`, `http:`, `mailto:`) — `javascript:` and `data:` execute.
- Session tokens live in httpOnly cookies, never in `localStorage`/`sessionStorage`.
- Never put secrets in client-exposed env vars (`NEXT_PUBLIC_*`, `VITE_*`, `REACT_APP_*`, `EXPO_PUBLIC_*`) — they are inlined into the shipped bundle.
- Never write a secret literal inside a `"use server"` function or code it calls; read `process.env` at call time — a 2025 RSC flaw let a crafted request return a Server Function's compiled source.
- Server Function return values are serialized to the caller: return only what the UI needs (`{ ok: true }`, a view object), never the ORM row.
- Native elements before ARIA: `<button>` for actions, `<a href>` for navigation, never `<div onClick>`. Move focus on route change and into a modal on open; return it on close.

### Bundle and hydration
- In app code import from the module file, not a barrel `index.ts` — a barrel pulls its whole module graph into the chunk.
- Lazy-load heavy, rarely shown or role-gated components (`React.lazy`, `next/dynamic`); `import()` paths are string literals, never template strings (bundlers can't analyze them).
- Load analytics, chat and other third-party scripts after hydration.
- `suppressHydrationWarning` only on a single leaf whose server and client values legitimately differ (a timestamp), never on a container.

## Test

- Use the repo's runner: Vitest (Vite projects) or Jest, with React Testing Library, `@testing-library/user-event`, MSW for HTTP and `jest-axe`/`vitest-axe`. Never add a second runner.
- Test what the user sees and does: render with production providers, act through `userEvent`, assert visible output and observable effects (callback arguments, request sent). Never assert internal state, render counts, hook calls or props passed to children.
- Query priority: `getByRole` (with `name`) → `getByLabelText` → `getByText` → `getByTestId` as a last resort. Never `container.querySelector`.
- `const user = userEvent.setup()` once per test and `await` every call; prefer it to `fireEvent`.
- Wait with `findBy*`, `waitFor` or `waitForElementToBeRemoved`; never `setTimeout` or a sleep.
- Mock HTTP at the network with MSW: `server.listen({ onUnhandledFrame: "error" })` (MSW 3; `onUnhandledRequest` on MSW 2), `server.resetHandlers()` in `afterEach`, `server.use(...)` per test for error responses. Never mock React, the `fetch`/axios module, or child components by default.
- Share one `renderWithProviders` helper. Create a fresh `QueryClient` per test with `retry: false`, outside the wrapper function — creating it inside resets the cache on every re-render.
- Test hooks with `renderHook` + `act` through their public API; pass a `wrapper` for context.
- For each interactive component cover the loading, error and empty states, and run axe: `expect(await axe(container)).toHaveNoViolations()`. JSDOM cannot check color contrast.
- Error-boundary tests silence `console.error` with a spy and restore it in `finally`.
- Treat `act(...)` warnings as bugs (an un-awaited update, or an update after unmount); never suppress them.
- No snapshots of component markup — they break on styling and get rubber-stamped. Snapshot only pure serialization output; use Playwright screenshots or Chromatic for visual diffs.
- RTL for hooks, presentational components and form logic; Playwright (component or E2E) for real layout, scrolling, drag-and-drop, clipboard, iframes and multi-page flows.

## Review
Every Build and Test rule above is also a review check. Also check for:
- A disabled or missing `eslint-plugin-react-hooks`, or a hook called conditionally or outside a component or custom hook.
- A stale closure: an async handler or interval reads a value that has since changed — use the functional updater or a ref.
- A Server Action (`"use server"`) or route handler that takes `FormData` or arguments without schema validation (zod, valibot, yup), or without an authentication and authorization check for that operation — it is a public endpoint.
- An RSC stack (Next.js App Router, React Router RSC, Waku, `@vitejs/plugin-rsc`, Parcel) resolving `react-server-dom-webpack|turbopack|parcel` below the latest patch of its 19.x line — check `npm audit` and the React security advisories. Unpatched lines allow unauthenticated RCE even with no Server Functions defined (CVE-2025-55182).
- A `"use client"` file importing a `server-only` module or a DB or secret-holding client; `"use client"` placed so high that a large non-interactive tree becomes client code (the directive propagates to imports).
- A Server Component passing a full record (password hash, tokens, internal fields) to a Client Component.
- Mutable module-level state in server code — shared across requests and users.
- `<img>` without `alt` (`alt=""` when decorative); ARIA misuse (`aria-label` on non-interactive elements, `role` overriding native semantics, disclosure widgets missing `aria-expanded`/`aria-controls`); color as the only indicator.
- A new inline object, array or function passed to a `memo` child; heavy synchronous work in render (parsing, sorting, regex compile).
- Form UI without a `<form>` element — it loses Enter-to-submit and native semantics.

## Verify

Prefer the repo's own scripts (`lint`, `typecheck`, `test`, `build` in `package.json`), run with the package manager its lockfile names (npm, pnpm, yarn, bun). Fallbacks:

```bash
npx tsc --noEmit                 # type check
npx eslint .                     # ESLint 9+ flat config; ESLint 10 ignores .eslintrc* and .eslintignore
npx vitest run [path]            # or: npx jest [path]; add --coverage for coverage
npx prettier --check .
```

- Lint with `eslint-plugin-react-hooks` 6+ `recommended`: besides `rules-of-hooks` and `exhaustive-deps` it runs compiler checks (`set-state-in-effect`, `refs`, `purity`, `immutability`, `static-components`) that enforce the state and effect rules. If it or `eslint-plugin-jsx-a11y` is missing, say so — a clean lint without them proves little.
- For SSR frameworks also run the production build; it catches server/client boundary and serialization errors that `tsc` and unit tests miss.
- On any `package.json` or lockfile change, apply the node skill's dependency and install-script rules.

## References

- `references/nextjs.md` — read for any Next.js App Router work: Server/Client Components, Server Actions, async `params`, caching in 15 and 16 (Cache Components), `proxy.ts` (16+), security config and Turbopack.
- `references/react-native.md` — read for React Native / Expo work: Expo Router params, lists, `<Text>` rules, styling, native APIs, secure storage and RN testing.
