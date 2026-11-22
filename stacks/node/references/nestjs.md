# NestJS

Applies to NestJS 11–12 on Express 5 or Fastify 5, validated with class-validator / class-transformer or a Standard Schema library (zod, valibot, ArkType). Nest 12 packages are ESM-only; CJS apps load them through `require(esm)` on Node 22.12+. Read together with the main skill; this file adds only NestJS-specific rules.

## Modules and structure
- One feature module per domain area, owning its controller, services, DTOs and repositories; keep DTOs next to the module that owns them. Cross-cutting guards, filters, interceptors and pipes live in a shared `common` area.
- Export only the providers other modules need. To use another module's provider, import that module — never list its provider in your own `providers`, because that silently creates a second instance with its own state and connections.
- Fix circular module dependencies by extracting a shared module; `forwardRef()` is a last resort and needs a comment saying why.
- Controllers stay thin: read input, call one service method, return a response DTO. No business logic, repository access, or multi-step write orchestration in controllers.

## Dependency injection
- Never `import type` a class that is constructor-injected — the decorator metadata needs the runtime value; with the import erased Nest sees `Object` and fails with "can't resolve dependencies".
- Providers are singletons by default: never store per-request data (user, tenant, transaction) on a service property. Use `AsyncLocalStorage` (e.g. `nestjs-cls`) for request context; use `Scope.REQUEST` sparingly — the scope spreads to every consumer and instantiates the chain per request.
- Inject interfaces and config through tokens (`@Inject(PAYMENT_GATEWAY)` with a `Symbol` or constant) — TypeScript interfaces do not exist at runtime.
- Create DB, cache and broker clients with async providers (`useFactory` + `inject`) so boot fails if they cannot connect, and close them in `onModuleDestroy`; call `app.enableShutdownHooks()` so that runs on `SIGTERM`.

## Bootstrap and validation
- Register validation, guards, filters and interceptors as `APP_PIPE` / `APP_GUARD` / `APP_FILTER` / `APP_INTERCEPTOR` providers rather than `app.useGlobal*()` — they then join DI and apply automatically in e2e tests built from the module.
  ```ts
  { provide: APP_PIPE, useValue: new ValidationPipe({
      whitelist: true, forbidNonWhitelisted: true, transform: true }) }
  ```
- Always set `whitelist` (plus `forbidNonWhitelisted` on public APIs) — without it, unknown properties such as `role` or `isAdmin` pass straight through to services and the ORM (mass assignment).
- Validation runs only when the parameter type is a class: `@Body() body: any`, an interface, or a type alias is never validated. Arrays (`@Body() items: CreateItemDto[]`) are not validated per element — use `ParseArrayPipe({ items: CreateItemDto })` or a wrapper DTO.
- With `StandardSchemaValidationPipe`, pass the schema through the `schema` option of `@Body()`/`@Query()`/`@Param()`, use only the parsed output, and bound strings and arrays in the schema as in a DTO.
- Do not rely on `enableImplicitConversion` for booleans — it turns the query string `'false'` into `true`. Use explicit `@Type(() => Number)` / `@Transform` on query DTOs.
- Parse route params with `ParseUUIDPipe` / `ParseIntPipe` instead of trusting raw strings.
- Express 5 routes: name wildcards (`@Get('files/*path')`, `forRoutes('{*splat}')`), use braces for optional segments, no regex characters — Nest 12 fails at startup on an invalid `forRoutes()`/`exclude()` entry.
- Express 5's default `simple` query parser drops nested keys: `?filter[status]=open` does not reach a nested query DTO unless the `query parser` setting is changed — then bound depth and size in the DTO.

## DTOs and serialization
- Every request DTO property carries a class-validator decorator. Nested objects need `@ValidateNested()` and `@Type(() => Child)` (`{ each: true }` for arrays); without `@Type` the nested object is not validated at all.
- Bound every string (`@MaxLength` / `@Length`) and array (`@ArrayMaxSize`) — unbounded input is a cheap denial-of-service.
- Build update DTOs with `PartialType` / `PickType` / `OmitType` (from `@nestjs/mapped-types` or `@nestjs/swagger`) so validation metadata is inherited, not copied by hand.
- Return dedicated response DTOs, or class instances with `@Exclude()` on sensitive fields under `ClassSerializerInterceptor`. Never return ORM entities directly. The interceptor ignores plain objects (e.g. Prisma results): `@Exclude` does nothing unless the value is converted first — `@SerializeOptions({ type: UserResponse })` on the handler, or `plainToInstance`.

## Auth and authorization
- Guards enforce coarse rules (authenticated, role). Ownership checks (`order.userId === user.id`) belong in the service, because a guard does not see the loaded resource.
- Know which default the app uses. With a global auth guard and a `@Public()` opt-out, scrutinise every new `@Public()`; with per-controller guards, every new controller or route needs one.
- List guards in dependency order: `@UseGuards(JwtAuthGuard, RolesGuard)` — the roles guard reads the `req.user` that the auth guard sets.
- Read the user through a typed `@CurrentUser()` param decorator or an `AuthenticatedRequest` type, not `@Req() req: any`.
- Rate-limit public and auth endpoints (`@nestjs/throttler`).

## Errors
- Keep one exception filter and one error envelope for the whole API. For non-`HttpException` errors the filter logs the full error and returns a generic 500 — never the exception message or stack.
- Throw domain errors from services and map them to HTTP in the filter; if the repo already throws Nest HTTP exceptions (`NotFoundException`, `ConflictException`) from services, stay consistent with it.
- Avoid `@Res()`: it switches the route to manual mode, bypasses interceptors and serialization, and hangs the request if a branch never sends. Use `@Res({ passthrough: true })` when you only need headers or cookies.

## Config
- `ConfigModule.forRoot({ isGlobal: true, validate })` with a schema, so boot fails on invalid env instead of starting partially. Nest 12 validates through Standard Schema (zod, valibot; Joi only v18+, options under `validationOptions.libraryOptions`).
- Read config through `ConfigService<Env, true>` with `get('PORT', { infer: true })`, or `registerAs` namespaces injected as `ConfigType<typeof dbConfig>`. Never read `process.env` inside providers.

## Persistence and transactions
- The service that owns the unit of work opens the transaction (`prisma.$transaction`, TypeORM `dataSource.transaction`) and passes the transactional client down; controllers never coordinate multi-step writes.
- TypeORM: `synchronize: false` everywhere except throwaway local databases — it can drop columns and data. Schema changes go through migrations.

## Testing
- Unit-test services by constructing them with fakes, or with `Test.createTestingModule({ providers: [UsersService, { provide: UsersRepository, useValue: fakeRepo }] })`.
- Use `.overrideGuard(...)` to bypass auth only in tests that are not about auth; keep at least one test per protected route that runs the real guard and asserts 401/403.
- e2e: compile the app from `AppModule` (or the feature module), call `createNestApplication()` and `init()`, drive it with supertest, and `await app.close()` in `afterAll` — open handles otherwise hang the runner.
- If globals are registered with `app.useGlobal*()` in `main.ts`, e2e setup must apply the same pipes, filters and guards, or tests pass against a different pipeline than production.
- Assert validation behaviour: unknown property → 400, missing or malformed field → 400, nested invalid object → 400.
- Under Vitest use `unplugin-swc` — esbuild does not emit decorator metadata, so DI fails in tests. Under Jest, Nest 12's ESM-only packages load only on Node 24.9+.

## Production defaults
- Structured logging with correlation ids (`nestjs-pino`, or `bufferLogs: true` plus `app.useLogger(...)`), health checks (`@nestjs/terminus`), `enableShutdownHooks()`.
- Nest 12 lowered limits (WebSocket `maxPayload` 1 MB, TCP `maxBufferSize`, 1000 multipart parts, empty TCP `host` = localhost). Raising one back needs a comment with the reason.
- `@nestjs/devtools-integration` stays at 0.2.1+ and `DevtoolsModule` is registered only in local development — older versions let any web page the developer visits run code on their machine.

## Review
Every rule above is also a review check, on top of the main skill's.
