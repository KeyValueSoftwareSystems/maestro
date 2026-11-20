---
name: java
description: Rules for writing, testing and reviewing Java 17/21/25 code, covering immutability, Optional, exceptions, concurrency, injection risks, JUnit Jupiter tests and a severity-graded review checklist. Use when building, testing or reviewing any Java code; Spring Boot, Spring Security and JPA rules are in the bundled spring-boot reference.
---

# Java

Covers: Java 17, 21 and 25 (LTS), JUnit Jupiter 5.x/6.x (6 needs Java 17), Mockito 5, AssertJ 3, Maven 3.9+ and Gradle 8/9.
If the repository's own conventions (its AGENTS.md/CLAUDE.md, build config, existing code)
disagree with this skill, follow the repository.

Read the build file first: `maven.compiler.release` or the Gradle toolchain version decides which
features you may use. Records, sealed types and `instanceof` patterns need 17; `switch` patterns,
record patterns and virtual threads need 21; statements before `super(...)`, `ScopedValue` and module
import declarations need 25. If it names `spring-boot`, also read `references/spring-boot.md`.

## Build

### Types and immutability
- Model DTOs, events, results and config as `record`s; give classes `final` fields and no setters unless a framework needs them — because immutable objects are thread-safe and never half-built.
- Validate invariants in the record's compact constructor, not in every caller.
- Copy incoming collections (`List.copyOf`) and never expose a mutable internal collection — because callers can mutate your state through it.
- Never use `double`/`float` for money or exact decimals; use `BigDecimal` built from a `String` or `valueOf`, and compare with `compareTo` — because `equals` says `2.0` and `2.00` differ.
- Use a `sealed` interface plus an exhaustive `switch` (21) for closed hierarchies, with no `default` branch — because `default` hides a newly added case from the compiler.
- Never enable preview features (`--enable-preview`) in production code — because structured concurrency, primitive patterns and lazy constants are still preview and change between releases.
- Never set `final` fields through reflection (`Field.setAccessible` + `set`), including in tests; inject through the constructor — because JDK 26 warns on it (JEP 500) and a later release will block it.

### Null and Optional
- Return `Optional<T>` from lookups that can miss; never return `null` for a single value from a public or service method, and never `null` for a collection — return an empty one.
- Never call `Optional.get()`; use `orElseThrow(() -> new OrderNotFoundException(id))`, `map`, or `orElse`.
- Never use `Optional` as a field, parameter or collection element — because it is not serialisable and adds a third "absent" state.
- Annotate nullness in new code with JSpecify (`org.jspecify.annotations.Nullable`, `@NullMarked`), never JSR 305 or `org.springframework.lang` annotations — because Spring Framework 7 and JUnit 6 use JSpecify and Framework 7 deprecates JSR 305.

### Exceptions
- Throw unchecked, domain-specific exceptions (`OrderNotFoundException`) for domain errors.
- Wrap checked technical exceptions with context and the original as the cause (`new StorageException("upload " + key, e)`) — because dropping the cause loses the stack trace.
- Never leave a catch block empty or continue silently. Handle, or rethrow; log once at the boundary, not log-and-rethrow at every layer — because duplicate stack traces bury the real one.
- Catch `Exception`/`Throwable` only at a top-level boundary (request handler, job runner, message listener).
- On `InterruptedException`, call `Thread.currentThread().interrupt()` before rethrowing or returning — because swallowing it breaks shutdown and cancellation.
- Open every stream, connection, result set and (21) `ExecutorService` in try-with-resources.

### Concurrency
- Never keep mutable state in static fields or shared singletons; keep instance fields `final` — because every request thread shares them. Use `ConcurrentHashMap`/atomics only for state that is genuinely shared.
- Never run blocking I/O on `CompletableFuture.supplyAsync(task)` without an executor (it uses the common ForkJoin pool); pass a bounded, named executor.
- On Java 21–23 virtual threads, do not hold `synchronized` across blocking I/O; use `ReentrantLock` — because it pins the carrier thread. JDK 24+ no longer pins (JEP 491), so do not rewrite `synchronized` on 25. Never pool virtual threads.

### Strings, streams, logging
- Log with SLF4J placeholders (`log.info("order_created id={}", id)`), never concatenation or `String.format`; pass the exception as the last argument so the stack trace is kept.
- Never log passwords, tokens, secrets, full card numbers or other PII; never use `System.out` or `printStackTrace()` in main code.
- `Stream.toList()` returns an unmodifiable list; use `collect(Collectors.toList())` only when the caller must mutate it.

### Untrusted input
- Never build SQL/JPQL from strings; use `PreparedStatement` or bind parameters — because concatenation is SQL injection. Allow-list identifiers that cannot be bound (sort columns, table names).
- Never pass user input to `Runtime.exec`/`ProcessBuilder` as a shell string; use the argument-list form with an allow-listed command and validated arguments.
- Never pass user input to `ScriptEngine.eval`, SpEL `parseExpression` or reflection (`Class.forName`) — because that is code injection.
- Resolve user-supplied paths against a base directory and reject escapes — because `../` reaches any file:

```java
Path base = uploadDir.toRealPath();
Path target = base.resolve(userFileName).normalize();
if (!target.startsWith(base)) throw new IllegalArgumentException("invalid path");
```

- Never deserialize untrusted data with `ObjectInputStream`, and never enable Jackson default typing or `@JsonTypeInfo(use = Id.CLASS)` on untrusted input.
- Disable DTDs and external entities on every XML parser that reads untrusted input (XXE).
- Never hardcode secrets, keys or passwords; read them from the environment or a secrets manager.
- Use `SecureRandom` for unguessable tokens and `MessageDigest.isEqual` to compare secrets.

### State machines and event handlers (payments, messaging)
- Check the idempotency key before any state mutation, not after processing.
- Guard every state transition with an explicit allowed-transitions table; reject illegal ones (`CANCELLED -> PROCESSING`).
- Make compensation atomic or idempotent so a partial failure can be retried.
- Add jitter to exponential backoff; give failed async messages a dead-letter path and an alert.

## Test
- Use JUnit Jupiter (`org.junit.jupiter.api.Test`) only; never JUnit 4 `@Test`/`@RunWith`/`SpringRunner` — because the Vintage engine is deprecated in JUnit 6, Testcontainers 2 dropped JUnit 4 and Spring Framework 7 deprecated its JUnit 4 support.
- Unit tests use `@ExtendWith(MockitoExtension.class)` with `@Mock`/`@InjectMocks` and no framework context. When strict stubs flag an unused stubbing, delete the stub; do not switch to `lenient()`.
- On JDK 21+, attach Mockito as a `-javaagent` in the Surefire `argLine` or the Gradle `test` task unless the build already does; never `-XX:+EnableDynamicAgentLoading` — because the JDK warns on dynamic agent loading and will disallow it (JEP 451).
- Mock only collaborators at the boundary (repositories, HTTP clients, clocks). Never mock records, value objects or the class under test, and avoid `spy` partial mocks.
- Inject a `Clock` (and an ID supplier) instead of calling `Instant.now()`/`UUID.randomUUID()` in logic — because tests must be deterministic.
- Assert with AssertJ: `assertThat(...)`, `assertThatThrownBy(...).isInstanceOf(...).hasMessageContaining(...)`; never `assertTrue(a.equals(b))`, which gives no diff on failure.
- Never `Thread.sleep` in tests; use Awaitility (`await().atMost(...).untilAsserted(...)`).
- Name tests for behaviour: `should_<outcome>_when_<condition>` (or the repository's pattern). `testFindUser` says nothing.
- Each test builds its own data (builders or factory methods); no order dependence and no shared mutable static state.
- Use `verify(...)` only when the interaction is the behaviour (a message sent, a payment charged); otherwise assert on returned or persisted state.
- For every bug fixed, add a regression test that fails before the fix; cover each error path (not found, invalid input, conflict) and boundaries (empty, null, max).

## Review
Grade each problem at the highest severity it matches.

### Critical: security
- SQL injection: string concatenation in JDBC, JPQL or native queries; unvalidated identifiers in `ORDER BY`.
- Command injection: user input reaching `ProcessBuilder` or `Runtime.exec()` without validation.
- Code injection: user input reaching `ScriptEngine.eval(...)`, SpEL or reflection.
- Path traversal: user input in `new File(...)`, `Paths.get(...)`, `FileInputStream(...)` without normalise + base-dir check.
- Unsafe parsing: `ObjectInputStream` on untrusted data, Jackson default typing, XML parsers with external entities enabled.
- Hardcoded secrets: API keys, passwords, tokens in source (test fixtures with fake values excepted).
- Sensitive logging: passwords, tokens or PII logged, especially near auth code, or echoed in error messages.
- Weak randomness: `java.util.Random`/`Math.random()` used for tokens or IDs that must be unguessable.

### Critical: error handling
- Swallowed exceptions: empty catch blocks, or `catch (Exception e) {}` that neither handles nor rethrows.
- `Optional.get()` without a presence check (`findById(id).get()`); use `orElseThrow`.
- Exception wrapped without its cause, or `InterruptedException` swallowed without restoring the interrupt flag.

### High
- Resource leak: stream, connection or executor not closed in try-with-resources.
- Money held in `double`/`float`, or `BigDecimal` compared with `equals`.
- Blocking I/O on the common ForkJoin pool (`supplyAsync` without an executor).
- Mutable collection exposed from an object that is meant to be immutable.
- `--enable-preview` in a production build; reflective writes to `final` fields.

### Medium
- Concurrency and state: non-final instance fields in singletons or static mutable state (race condition); unbounded async execution.
- Idioms: `null` returned from the service layer instead of `Optional`; `Optional` as a field or parameter; JSR 305 nullness annotations in new code.
- Logging: concatenation in log calls; `System.out`/`printStackTrace()`; log-and-rethrow at every layer.
- Testing: service tests without `MockitoExtension`; `Thread.sleep()` instead of Awaitility; weak names like `testFindUser`; partial mocks; tests depending on wall-clock time or execution order.
- State machines and event handlers: idempotency checked after processing; unguarded transitions; compensation that can partially succeed; backoff without jitter; no dead-letter path or alert.

## Verify
Prefer the repository's wrapper (`./mvnw`, `./gradlew`) over a global `mvn`/`gradle` — because the wrapper pins the build-tool version the project is tested with.

```bash
./mvnw -q verify                                   # compile, tests, configured checks
./mvnw -q test -Dtest=OrderServiceTest             # one class while iterating
./gradlew build                                    # compile, test, check
./gradlew test --tests 'com.example.OrderServiceTest'
```

- Run static analysis only where the build configures it: `./mvnw checkstyle:check spotbugs:check pmd:check` or `./gradlew checkstyleMain spotbugsMain pmdMain`; format check `./mvnw spotless:check` / `./gradlew spotlessCheck`.
- Dependency CVEs, when the plugin is configured: `./mvnw org.owasp:dependency-check-maven:check` or `./gradlew dependencyCheckAnalyze`.
- Pin the build tool and artifacts: keep `wrapperSha256Sum`/`distributionSha256Sum` in `.mvn/wrapper/maven-wrapper.properties`, and for Gradle update `gradle/verification-metadata.xml` (`./gradlew --write-verification-metadata sha256`) with every dependency change — because a swapped artifact with the same coordinates otherwise downloads silently.
- Coverage with JaCoCo (`./mvnw verify` with the plugin bound, or `./gradlew jacocoTestReport`): keep the repository's threshold; if none is set, aim for 80% line coverage on changed code.
- Never report done with failing tests, new compiler warnings, or tests skipped (`-DskipTests`, `@Disabled`) to get green.
- Before handing off, read `git diff` for leftover `System.out`, commented-out code, stray TODOs and `@Disabled`.

## References
- `references/spring-boot.md`: read when the build uses Spring Boot (starter parent, plugin or BOM). It covers controllers, services, `@Transactional`, validation, Spring Security, JPA/Hibernate and Spring Data, slice tests with Testcontainers, the Spring-specific review checklist, and Spring verification steps.
