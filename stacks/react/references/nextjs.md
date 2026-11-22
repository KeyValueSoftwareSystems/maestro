# Next.js (App Router)

Applies to Next.js 15–16 with the App Router (React 19). Next.js 14 and older get no security fixes — flag them for upgrade. Several defaults changed between majors, so read `next` in `package.json` before applying a version-marked rule. Everything in the main skill still applies.

## Server and Client Components

- Components are Server Components by default. Put `"use client"` only on the leaf that needs state, effects, event handlers or browser APIs — every module that file imports becomes client code too.
- Never put `"use client"` on a `page.tsx` or `layout.tsx` to "make it work"; extract the interactive part into its own client file.
- Never import a Server Component into a Client Component file; pass it in as `children` or another prop.
- Props crossing the boundary must be serializable — no functions other than Server Actions, no class instances.
- Pass Client Components only the fields they render; map DB records to a small view object first. Everything passed is visible in the RSC payload in the page source.
- Add `import "server-only"` to every module that touches the database, secrets or private APIs, so a client import fails the build instead of leaking.
- Never keep mutable module-level state in server code (a "current user" variable, a per-user cache map) — module scope is shared by all concurrent requests. Use `cookies()`, `headers()`, `React.cache` or request-scoped storage.

## Route props (15+)

- `params` and `searchParams` are Promises: `const { id } = await params`. Synchronous access warns in 15 and is removed in 16. The same applies to `cookies()`, `headers()` and `draftMode()`.
- Treat `params` and `searchParams` as untrusted input — validate with a schema before they reach a query.

```tsx
type Props = { params: Promise<{ id: string }> };
export default async function Page({ params }: Props) {
  const { id } = IdSchema.parse(await params);
  const product = await getProduct(id);
  if (!product) notFound();
  return <ProductView product={toProductView(product)} />;
}
```

## Data fetching and caching

- Remove waterfalls: `Promise.all` for independent calls, or split the page into sibling async components, each under its own `<Suspense>`, so they run in parallel and stream.
- Wrap non-`fetch` data functions (ORM, SDK calls) in `React.cache` to dedupe them within one request.
- Caching defaults differ by version — follow the model the repo uses, and don't mix them:
  - 15, and 16 without `cacheComponents`: nothing is cached by default; opt in with `cache: "force-cache"` or `next: { revalidate: n }`.
  - 16 with `cacheComponents` (set `partialPrefetching` explicitly too): nothing is cached outside `"use cache"` + `cacheLife`/`cacheTag`. Delete `dynamic`, `revalidate`, `fetchCache`, `dynamicParams` and `runtime` segment exports — they error. Read `cookies()`, `headers()`, `params` and `searchParams` in a child under `<Suspense>`.
- A `"use cache"` function cannot read `cookies()`/`headers()`; read them outside and pass the values in. Its key is its arguments plus captured variables, so pass user or tenant ids explicitly and authorize before the call — never inside it.
- Exports of a file-level `"use cache"` module are callable from Client Components like Server Functions: never export one that takes an id without its own authorization check.
- After every mutation, revalidate each view that shows the data (`revalidatePath`, `revalidateTag`). In 16, `revalidateTag(tag, "max")` needs the profile argument (one-arg form is deprecated); `updateTag(tag)` gives read-your-writes but throws outside a Server Action — use `revalidateTag` in Route Handlers and webhooks.
- Use `after()` from `next/server` (15.1+) for logging, analytics or cache warming that must not delay the response.

## Server Actions and Route Handlers

- Every export of a `"use server"` file is a public POST endpoint callable with any arguments. Export only actions from it — never helpers.
- In each action, in this order: authenticate, validate input with a schema, authorize the specific record. Never trust ids, roles or prices from hidden fields, or the UI having hidden the button.

```ts
"use server";
export async function deletePost(formData: FormData) {
  const session = await auth();
  if (!session) throw new Error("Unauthorized");
  const { id } = DeleteSchema.parse(Object.fromEntries(formData));
  const post = await db.post.findUnique({ where: { id } });
  if (post?.authorId !== session.user.id) throw new Error("Forbidden");
  await db.post.delete({ where: { id } });
}
```

- Return expected failures as values (`{ error: "…" }`) for `useActionState`; throw only for unexpected ones. A page-level auth check does not cover the actions defined in that page.
- Route Handlers get the same validation, authentication and authorization as any API endpoint.

## Middleware / proxy

- 16+: `proxy.ts` at the project root (or `src/`), exporting `proxy` or a default; it runs only on Node.js, and exporting `runtime` throws. `middleware.ts` still works on 16 but is deprecated — keep it only for the Edge runtime, and never rename Edge middleware to `proxy.ts` blindly. Never flag `proxy.ts` as misnamed.
- Never make middleware/proxy the only authorization check — re-check in the action or data layer. Server Functions are POSTs to the page's route, so a matcher that skips a path skips its actions too. Middleware bypasses have shipped before (CVE-2025-29927).
- Forward changed request headers with `NextResponse.next({ request: { headers } })`; never `NextResponse.next({ headers: request.headers })` — that copies request headers onto the response and has enabled SSRF.

## Config security

- Never build a `rewrites()`/`redirects()` destination hostname from request input (`:param`, `has` captures) — it allows SSRF and open redirects.
- `images.remotePatterns` lists exact `https` hostnames with a `pathname` prefix — no `**` hosts and no deprecated `images.domains`. `dangerouslyAllowSVG` and `dangerouslyAllowLocalIP` need a comment naming the threat — the image optimizer has had SSRF and RCE flaws.

## Client bundle and hydration

- Add barrel-heavy libraries that aren't on Next's default list to `experimental.optimizePackageImports` instead of rewriting every import.
- `next/dynamic(() => import(...), { ssr: false })` only inside a Client Component — 15+ rejects it in Server Components.
- Load third-party scripts with `next/script` and `strategy="afterInteractive"` or `"lazyOnload"`, not a raw `<script>` in the layout.
- `NEXT_PUBLIC_*` values are inlined at build time: public to everyone, and changing one needs a rebuild.
- Values needed before hydration (theme, locale) are set by a small inline script on `document.documentElement`; `suppressHydrationWarning` goes on `<html>` for that, or on a single leaf — never on a subtree.

## Turbopack

- 15: `next dev --turbopack` is stable. 16+: Turbopack is the default for `next dev` and `next build`; opt out with `--webpack`.
- On 16, `next build` fails when a `webpack()` config exists (often added by a plugin) unless `--webpack` or `--turbopack` is passed. Port loaders to `turbopack.rules`/`turbopack.resolveAlias`, or keep `--webpack` in the script explicitly.
- For bundle size use `next analyze` (16.1+, Turbopack) or `@next/bundle-analyzer` (webpack builds).

## Testing

- Vitest and Jest cannot reliably render async Server Components. Cover those pages with Playwright, and unit-test their data functions and Server Actions as plain async functions.
- Server Action tests call the action with a `FormData` and assert: invalid input is rejected, an unauthenticated call is refused, and a non-owner is refused.
- Client Components test with RTL as usual. `next/navigation` (`useRouter`, `usePathname`, `useSearchParams`) needs a mock such as `next-router-mock/navigation` — the App Router context does not exist outside Next.

## Review
Every rule above is also a review check. Also check that `next` is on the latest patch of its 15.x/16.x line: check `npm audit` and the Next.js security advisories (monthly releases), and treat the 16.4+ `next dev`/`next build` vulnerability warning as a failure.

## Verify

```bash
next build        # type-checks, catches boundary/serialization errors; since 16 no lint, no route sizes
npx eslint .      # `next lint` is deprecated in 15.5 and removed in 16
next analyze      # 16.1+ bundle analysis (Turbopack)
```

Prefer the repo's scripts; run Playwright for Server Component pages.
