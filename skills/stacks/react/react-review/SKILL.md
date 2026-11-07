---
name: react-review
description: React review checklist — what to check in React code, by severity. A reference for writing and reviewing it; in a workflow run the review step records each problem as a finding and the engine decides what blocks.
allowed-tools: Read, Grep, Glob, Bash
tags: [stack:react, review]
---

# React review checklist

Use this when writing or reviewing React code. The severities say how serious a problem is; they are guidance for a finding's severity, not a verdict.

## Review Priorities (React-specific only)

### CRITICAL -- React Security

- **`dangerouslySetInnerHTML` with unsanitized input**: User-controlled HTML rendered without DOMPurify or equivalent allowlist sanitizer. Halt review until source is documented and sanitization is at the same call site.
- **`href` / `src` with unvalidated user URLs**: `javascript:` and `data:` schemes execute code. Require URL scheme validation.
- **Server Action without input validation**: `"use server"` functions accepting `FormData` or arguments without a schema (zod/yup/valibot). Treat as a public API endpoint.
- **Secret in client bundle**: `NEXT_PUBLIC_*`, `VITE_*`, `REACT_APP_*`, or any client-imported env var holding a private key, token, or service-side secret.
- **`localStorage`/`sessionStorage` for session tokens**: Accessible to any XSS. Require httpOnly cookies.

### CRITICAL -- Hook Rules

- **Conditional hook call**: Hook inside `if`, `for`, `&&`, ternary, or after early return. `eslint-plugin-react-hooks` should already catch this; flag if the lint rule is disabled.
- **Hook called outside a component or custom hook**: `useState` in a regular function.
- **Mutating state directly**: `state.push(x)`, `obj.foo = 1` followed by `setObj(obj)`. Mutation does not trigger re-render and breaks `===` checks in memoized children.

### HIGH -- Hook Correctness

- **Missing dependency in `useEffect`/`useMemo`/`useCallback`**: Reactive value referenced inside but absent from the dep array. Flag every `// eslint-disable-next-line react-hooks/exhaustive-deps` without a justification comment.
- **Effect for derived state**: `setX(computed(props.y))` inside `useEffect([props.y])`. Compute during render instead.
- **Effect missing cleanup**: Subscriptions, intervals, listeners, fetch without `AbortController`.
- **Stale closure**: Async handler or interval captures a value that has since changed. Fix with functional updater or ref.
- **Custom hook not prefixed `use`**: Breaks lint detection — rename.

### HIGH -- Server/Client Boundary (Next.js App Router / RSC)

- **Server-only import in Client Component**: `"use client"` file imports a module marked `"server-only"` or known DB client (Prisma client root, AWS SDK with secrets).
- **`"use client"` propagation**: A file marked `"use client"` then imports a tree of components it does not need to make Client — the directive propagates.
- **Sensitive data leaked via props**: Server Component passes a full user record (including hashed passwords, tokens) to a Client Component.
- **Server Action without auth check**: `"use server"` function accessible without confirming the current user has authorization for the operation.

### HIGH -- Accessibility

- **Interactive element without keyboard reachability**: `<div onClick>` instead of `<button>`. Mouse-only interaction excludes keyboard and assistive-tech users.
- **Form input without label**: `<input>` without an associated `<label htmlFor>` or `aria-label`/`aria-labelledby`.
- **Missing `alt` on `<img>`**: Decorative images need `alt=""`, content images need a description.
- **`target="_blank"` without `rel="noopener noreferrer"`**: Window opener hijack risk.
- **Misuse of ARIA**: `aria-label` on non-interactive element, `role` overriding native semantics, missing `aria-controls` / `aria-expanded` on disclosure widgets.
- **Heading order violation**: Skipping levels (`<h1>` then `<h3>`).
- **Color used as sole indicator**: Errors signaled only by red text without an icon or text label.

### HIGH -- Rendering and State Correctness

- **`key={index}` in dynamic list**: Reordering, insertion, or deletion attaches state to the wrong row. Use stable database IDs.
- **Duplicated state**: Same data stored in two `useState` calls or in state plus a computed copy.
- **`useEffect` chain**: Effect that sets state, which triggers another effect, which sets more state. Refactor to derive during render or consolidate.
- **Initializing state from a prop without `key`**: Component does not reset when the prop changes; fix with `key={propValue}` on the parent.

### MEDIUM -- Performance

- **Over-memoization**: `useMemo`/`useCallback` without a measured win — props change on most renders, or the value is not used by a memoized child or another hook's deps.
- **New object/function inline as prop to memoized child**: Defeats `React.memo`.
- **Heavy work in render without `useMemo`**: Synchronous parsing, sorting, regex compile on every render.
- **Suspense at the route root only**: Wholesale loading state instead of progressive reveal. Push boundaries closer to the data.
- **Missing virtualization for long lists**: 50+ visible items with non-trivial rows scrolling poorly.
- **`useContext` for high-frequency value**: All consumers re-render on every change.

### MEDIUM -- Forms

- **Form without semantic `<form>` element**: Loses native submit-on-Enter, browser form integration, accessibility tree.
- **`onSubmit` without `preventDefault()`**: Page navigates, state lost (unless using React 19 form actions, which handle it).
- **Roll-your-own validation in non-trivial form**: Recommend React Hook Form, TanStack Form, or React 19 `useActionState`.
- **Missing `name` attribute on inputs inside a form**: Cannot be read via `FormData`.

### MEDIUM -- Composition

- **Prop drilling beyond 3 levels**: Consider Context or composition with `children` instead.
- **Component over 200 lines**: Extract subcomponents or a custom hook.
- **Class component in new code**: Convert to function component when modifying.

## Diagnostic Commands

```bash
# Required
npx eslint . --ext .tsx,.jsx                          # ensure eslint-plugin-react-hooks is configured
npm run typecheck --if-present                        # respect project's canonical command
tsc --noEmit -p <tsconfig>                            # fallback if no script

# Useful
npx eslint . --ext .tsx,.jsx --rule 'react-hooks/exhaustive-deps: error'
npx eslint . --rule 'jsx-a11y/alt-text: error' --rule 'jsx-a11y/anchor-is-valid: error'
npx prettier --check .
npm audit                                             # supply-chain advisories
```

If `eslint-plugin-react-hooks` or `eslint-plugin-jsx-a11y` is not in the project, recommend installing during the review.
