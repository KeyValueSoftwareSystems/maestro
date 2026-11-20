# Spring Boot, Spring Security and JPA

Covers: Spring Boot 4.0–4.2 (Spring Framework 7.0/7.1, Spring Security 7.x), Spring Data JPA on
Jakarta Persistence 3.2 / Hibernate 7, Testcontainers 2. Boot 3.x is out of OSS support; on a 3.5 repo,
rules marked "Boot 4" do not apply. These rules sit on top of the base Java skill.
Check the Boot version in `pom.xml`/`build.gradle` first; version-specific rules say which version they need.

## Build

### Layers and injection
- Use constructor injection with `final` fields (a single constructor needs no `@Autowired`); never `@Autowired` on fields — because field injection hides dependencies and blocks plain unit tests.
- Never return JPA entities from controllers or bind them as `@RequestBody`; map to and from records — because entities leak lazy proxies and internal fields and allow mass assignment.
- Bind configuration with `@ConfigurationProperties` records plus `@Validated`, not scattered `@Value` strings.
- Manage Spring versions through the Boot BOM/parent; never pin individual Spring module versions — because mismatched modules fail at runtime.
- On Boot 4 use the modular starters: `spring-boot-starter-webmvc` (not the deprecated `-web`), `spring-boot-starter-flyway`/`-liquibase` next to the migration library, and the matching `spring-boot-starter-<tech>-test`; drop `spring-boot-starter-classic` once migrated.
- Call HTTP services with `RestClient` or `@ImportHttpServices` interface clients; never add new `RestTemplate`/`RestTemplateBuilder` code — because Framework 7.1 and Boot 4.2 deprecate them.
- On Boot 4 use Jackson 3 (`tools.jackson.*`; annotations stay in `com.fasterxml.jackson.annotation`) and customize it with a `JsonMapper` bean or `JsonMapperBuilderCustomizer` — because an `ObjectMapper` bean no longer replaces the auto-configured mapper.

### Transactions and proxies
- Put `@Transactional` on public service methods, with `@Transactional(readOnly = true)` on read-only ones; never on controllers.
- `@Transactional`, `@Async`, `@Cacheable` and `@PreAuthorize` work only through the Spring proxy: on `private` methods or on calls from another method in the same class they are silently ignored. Move the method to another bean.
- Checked exceptions do not roll back by default; throw unchecked exceptions or set `rollbackFor = Exception.class`.
- Keep transactions short: no remote HTTP calls, message sends or waits inside them. Run side effects after commit with `@TransactionalEventListener(phase = AFTER_COMMIT)`.
- Set `spring.jpa.open-in-view=false` — because the default holds a DB connection for the whole request and hides lazy loading outside transactions.

### REST and errors
- Put `@Valid` on every `@RequestBody` with constraints on the DTO record; add `@Validated` on the controller for constrained `@PathVariable`/`@RequestParam`.
- Handle errors once in a `@RestControllerAdvice` returning `ProblemDetail` (RFC 9457; `spring.mvc.problemdetails.enabled=true`). Log unexpected exceptions and return a generic 500 — never `e.getMessage()` or a stack trace to the client.
- List endpoints take `Pageable` and return a page, never an unbounded `List<T>`; cap the size with `spring.data.web.pageable.max-page-size`.

### JPA and Hibernate
- Map every association `fetch = LAZY`. `@ManyToOne` and `@OneToOne` default to EAGER, so set LAZY explicitly — because EAGER causes N+1 queries.
- Load what a use case needs with `JOIN FETCH` or `@EntityGraph`, or read through a DTO/interface projection.
- Never combine a collection `JOIN FETCH` with pagination — because Hibernate then pages in memory. Page the IDs first, then fetch; set `hibernate.query.fail_on_pagination_over_collection_fetch=true`.
- Mutating `@Query` methods need `@Modifying` and a transaction; add `clearAutomatically = true` when the persistence context is used afterwards.
- Use `:named` bind parameters in JPQL and native queries, never concatenation; send client-chosen sort fields through an allow-list.
- Use `@Enumerated(EnumType.STRING)`, never the ORDINAL default — because reordering the enum corrupts stored data.
- Never use Lombok `@Data`/`@EqualsAndHashCode` on entities. Base `equals` on a business key, or on the id with a null check and a constant `hashCode` — because generated versions touch lazy associations and change when the id is assigned.
- Use `CascadeType.ALL`/`REMOVE` and `orphanRemoval` only on true parent-child aggregates; never cascade remove across `@ManyToMany`.
- Change the schema only through Flyway or Liquibase migrations; keep `spring.jpa.hibernate.ddl-auto` at `validate` or `none` outside local dev. Never edit an applied migration; add a new one.
- Use `persist`, `merge`, `remove` and `getReference`; never `Session.save`/`update`/`saveOrUpdate`/`delete`/`load`, `@Where` (use `@SQLRestriction`), `@Proxy` or `CascadeType.SAVE_UPDATE` — because Hibernate 7 removed them.
- For bulk inserts set `hibernate.jdbc.batch_size` and `order_inserts`; `GenerationType.IDENTITY` disables insert batching, so use `SEQUENCE` where batching matters.

### Spring Security
- Configure a `SecurityFilterChain` bean with the lambda DSL and `authorizeHttpRequests`; Security 7 removed `.and()` chaining, `authorizeRequests`, `AntPathRequestMatcher` and `MvcRequestMatcher` (use `PathPatternRequestMatcher`).
- Deny by default: list public paths with `permitAll()` and end with `.anyRequest().authenticated()`.
- Authorize every sensitive endpoint, including object ownership, with `@EnableMethodSecurity` and `@PreAuthorize("@authz.isOwner(#id, authentication)")` — because a role check alone allows IDOR.
- Prefer `oauth2ResourceServer(o -> o.jwt(...))` over a hand-written JWT filter. A custom filter must verify signature, expiry, issuer and audience, and reject `alg: none`.
- Hash passwords through a `PasswordEncoder` bean (delegating, BCrypt or Argon2); never store or compare plaintext.
- CSRF: keep it on for cookie/session-authenticated browser apps. Disable it only for stateless bearer-token APIs with `SessionCreationPolicy.STATELESS`, and comment why.
- Configure CORS in the security chain with explicit origins; never `*` or `allowedOriginPatterns("*")` together with `allowCredentials(true)`.
- Session cookies are `HttpOnly`, `Secure` and `SameSite`; keep the default security headers and add a CSP for apps that serve HTML.
- Load secrets through `${ENV_VAR}` placeholders or a vault; never commit credentials in `application*.yml`/`.properties`.
- Expose only `health` and `info` actuator endpoints publicly; never `management.endpoints.web.exposure.include=*` unauthenticated — because `env`, `heapdump` and `loggers` leak secrets.
- Rate-limit login and expensive endpoints, returning `429`. Key clients on `request.getRemoteAddr()`; never read `X-Forwarded-For` directly — because clients can spoof it.
- Behind a trusted proxy, set `server.request.header.forwarded.strategy` (Boot 4.2+; `server.forward-headers-strategy` before, never both), or a `ForwardedHeaderFilter` bean for WAR deployments.
- File uploads: cap size (`spring.servlet.multipart.max-file-size`), validate content type and extension, and store outside the web root under a generated name.

### Async, scheduling, messaging
- `@Async` needs `@EnableAsync` and `@Cacheable` needs `@EnableCaching`. Bound the async executor (`spring.task.execution.pool.queue-capacity` or your own `ThreadPoolTaskExecutor`) — because the default queue is unbounded. With `spring.threads.virtual.enabled=true` the pool properties are ignored; set `spring.task.execution.simple.concurrency-limit`.
- The default scheduler has one thread: long `@Scheduled` jobs block all others. Raise `spring.task.scheduling.pool.size` or hand off, and lock jobs that must run on one instance (for example ShedLock).
- Retry only idempotent operations with Spring Framework 7 `@Retryable` (enabled by `@EnableResilientMethods`), always narrowing `includes` and setting `multiplier` and `jitter` — because the default retries every exception 3 times at a fixed 1 s delay. Spring Retry is archived; keep Resilience4j where already used.
- Kafka/AMQP listeners need an error handler with a dead-letter topic or queue.

## Test
- Pick the narrowest slice: plain JUnit + Mockito for services, `@WebMvcTest(XController.class)` for controllers, `@DataJpaTest` for repositories, `@SpringBootTest` only for end-to-end flows — because a full context is slow and hides which beans a test needs.
- Replace beans with `@MockitoBean`/`@MockitoSpyBean` on test-class fields or as type-level `@MockitoBean(types = ...)`, never in `@Configuration` classes. `@MockBean`/`@SpyBean` were deprecated in Boot 3.4 and removed in 4.0, as was `MockitoTestExecutionListener`, so plain `@Mock` fields need `MockitoExtension`.
- On Boot 4 add `@AutoConfigureMockMvc` to `@SpringBootTest` classes that use MockMvc, and test HTTP with `RestTestClient` (`@AutoConfigureRestTestClient`) — because `@SpringBootTest` no longer provides MockMvc or `TestRestTemplate`, which 4.2 deprecates.
- Controller tests assert status, JSON body (`jsonPath`), validation failures (400), and security: 401 unauthenticated, 403 wrong role or other owner (`@WithMockUser`, `with(csrf())`).
- Run repository and integration tests against the production database engine with Testcontainers 2 (`org.testcontainers.postgresql.PostgreSQLContainer`, `testcontainers-<module>` artifacts), wired by `@ServiceConnection` or `@DynamicPropertySource`, plus `@AutoConfigureTestDatabase(replace = NONE)` on `@DataJpaTest`. Do not use H2 as a stand-in — because dialect differences hide real bugs.
- Test custom queries and fetch plans: assert the result and the query count (Hibernate statistics or SQL logging), not only that it runs.
- Do not test transaction boundaries or lazy loading inside a test-managed `@Transactional`; the test transaction rolls back and keeps the session open, which hides commit-time and lazy-init failures.
- Keep the set of `@MockitoBean`/property overrides consistent across tests; each distinct combination builds a new application context and slows the suite.

## Review
Grade each problem at the highest severity it matches.

### Critical: security
- SQL injection: string concatenation in `@Query`, `JdbcTemplate`, `NamedParameterJdbcTemplate` or `EntityManager.createNativeQuery()`.
- Missing input validation: `@RequestBody` without `@Valid`, or an entity bound straight from the request (mass assignment).
- Missing authorization: endpoint or service method with no check, ownership not verified, chain not deny-by-default, or `permitAll()` wider than intended.
- CSRF disabled on a session/cookie-authenticated app, or disabled without a documented reason (stateless JWT APIs may omit it).
- Hardcoded secrets in source or `application*.yml`/`.properties` (use environment, Vault or a cloud secrets manager); actuator endpoints beyond health/info exposed unauthenticated.
- Plaintext or weak (MD5, SHA-1, unsalted) password storage; JWT accepted without signature and expiry checks.
- CORS `*` with credentials; rate limiting keyed on raw `X-Forwarded-For`.
- Tokens or PII logged through SLF4J; `e.getMessage()` or stack traces returned to clients.

### Critical: error handling
- `repository.findById(id).get()` instead of `orElseThrow`.
- Wrong HTTP status: `200` with a null body instead of `404`, or a create without `201`.

### High: architecture
- `@Autowired` field injection instead of constructor injection.
- Business logic in controllers instead of delegating to the service layer.
- `@Transactional` on a controller or repository instead of the service; missing `readOnly = true` on read-only service methods; `@Transactional` on a private or self-invoked method (no effect).
- JPA entity returned from a controller instead of a DTO or record projection.
- Remote call or message send inside a transaction; `open-in-view` left enabled.

### High: JPA and relational database
- N+1 queries: `FetchType.EAGER` on collections or default-EAGER `@ManyToOne` read in loops; fix with `JOIN FETCH`, `@EntityGraph` or a projection.
- Unbounded list endpoint: `List<T>` returned without `Pageable` and `Page<T>`.
- Mutating `@Query` without `@Modifying` + `@Transactional`.
- Dangerous cascade: `CascadeType.ALL` with `orphanRemoval = true`; confirm the intent is deliberate.
- Collection fetch join combined with pagination (in-memory paging).
- `EnumType.ORDINAL`; `ddl-auto=update`/`create` outside local dev; an applied migration edited.

### Medium
- Concurrency: `@Async` or `CompletableFuture` without a bounded executor; long-running `@Scheduled` methods blocking the scheduler thread.
- Testing: `@SpringBootTest` for unit tests (use `@WebMvcTest`/`@DataJpaTest`); service tests not on `MockitoExtension`; H2 standing in for the production database; `@MockBean`/`@SpyBean`.
- HTTP clients: new `RestTemplate` or `TestRestTemplate` code instead of `RestClient`/`RestTestClient`.
- Resilience: `@Retryable` without `includes` or jitter; Spring Retry in new code; Kafka/AMQP listeners without dead-letter handling.
- NoSQL (Spring Data MongoDB): document shape changed without a versioned migration; large blobs embedded (16 MB BSON limit); time-bound data without a TTL index; queries on unindexed fields; `findAll()` without paging; connection settings still under `spring.data.mongodb.*` on Boot 4 (moved to `spring.mongodb.*`).

## Verify
- `./mvnw verify` (or `./gradlew build`) runs unit, slice and Testcontainers tests. Maven runs `*IT` classes only in `verify` via Failsafe, so `./mvnw test` alone is not a full check.
- Testcontainers needs a running Docker daemon; if it is unavailable, report those tests as not run rather than passed.
- Start the app once with the intended profile (`./mvnw spring-boot:run` or `./gradlew bootRun`) — because it catches missing beans, bad config properties and failing migrations that slice tests miss.
- Grep the diff for `System.out`, `e.getMessage()` in responses, `allowedOrigins("*")`, `@Autowired` fields, `FetchType.EAGER`, `ddl-auto`, `csrf(...disable`, `RestTemplate`, `@MockBean` and hardcoded passwords.
- Run the dependency CVE check when configured, and keep Spring Boot on a supported release line at its latest patch — check the Spring Boot support page.
