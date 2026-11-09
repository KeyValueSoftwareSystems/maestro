---
name: kotlin-review
description: Kotlin review checklist — what to check in Kotlin code, by severity. A reference for writing and reviewing it; in a workflow run the review step records each problem as a finding and the engine decides what blocks.
allowed-tools: Read, Grep, Glob, Bash
tags: [stack:kotlin, review]
---

# Kotlin review checklist

Use this when writing or reviewing Kotlin code. The severities say how serious a problem is; they are guidance for a finding's severity, not a verdict.

## Review Checklist

### Architecture (CRITICAL)

- **Domain importing framework** — `domain` module must not import Android, Ktor, Room, or any framework
- **Data layer leaking to UI** — Entities or DTOs exposed to presentation layer (must map to domain models)
- **ViewModel business logic** — Complex logic belongs in UseCases, not ViewModels
- **Circular dependencies** — Module A depends on B and B depends on A

### Coroutines & Flows (HIGH)

- **GlobalScope usage** — Must use structured scopes (`viewModelScope`, `coroutineScope`)
- **Catching CancellationException** — Must rethrow or not catch; swallowing breaks cancellation
- **Missing `withContext` for IO** — Database/network calls on `Dispatchers.Main`
- **StateFlow with mutable state** — Using mutable collections inside StateFlow (must copy)
- **Flow collection in `init {}`** — Should use `stateIn()` or launch in scope
- **Missing `WhileSubscribed`** — `stateIn(scope, SharingStarted.Eagerly)` when `WhileSubscribed` is appropriate

```kotlin
// BAD — swallows cancellation
try { fetchData() } catch (e: Exception) { log(e) }

// GOOD — preserves cancellation
try { fetchData() } catch (e: CancellationException) { throw e } catch (e: Exception) { log(e) }
// or use runCatching and check
```

### Compose (HIGH)

- **Unstable parameters** — Composables receiving mutable types cause unnecessary recomposition
- **Side effects outside LaunchedEffect** — Network/DB calls must be in `LaunchedEffect` or ViewModel
- **NavController passed deep** — Pass lambdas instead of `NavController` references
- **Missing `key()` in LazyColumn** — Items without stable keys cause poor performance
- **`remember` with missing keys** — Computation not recalculated when dependencies change
- **Object allocation in parameters** — Creating objects inline causes recomposition

```kotlin
// BAD — new lambda every recomposition
Button(onClick = { viewModel.doThing(item.id) })

// GOOD — stable reference
val onClick = remember(item.id) { { viewModel.doThing(item.id) } }
Button(onClick = onClick)
```

### Kotlin Idioms (MEDIUM)

- **`!!` usage** — Non-null assertion; prefer `?.`, `?:`, `requireNotNull`, or `checkNotNull`
- **`var` where `val` works** — Prefer immutability
- **Java-style patterns** — Static utility classes (use top-level functions), getters/setters (use properties)
- **String concatenation** — Use string templates `"Hello $name"` instead of `"Hello " + name`
- **`when` without exhaustive branches** — Sealed classes/interfaces should use exhaustive `when`
- **Mutable collections exposed** — Return `List` not `MutableList` from public APIs

### Android Specific (MEDIUM)

- **Context leaks** — Storing `Activity` or `Fragment` references in singletons/ViewModels
- **Missing ProGuard rules** — Serialized classes without `@Keep` or ProGuard rules
- **Hardcoded strings** — User-facing strings not in `strings.xml` or Compose resources
- **Missing lifecycle handling** — Collecting Flows in Activities without `repeatOnLifecycle`

### Security (CRITICAL)

- **Exported component exposure** — Activities, services, or receivers exported without proper guards
- **Insecure crypto/storage** — Homegrown crypto, plaintext secrets, or weak keystore usage
- **Unsafe WebView/network config** — JavaScript bridges, cleartext traffic, permissive trust settings
- **Sensitive logging** — Tokens, credentials, PII, or secrets emitted to logs


### Gradle & Build (LOW)

- **Version catalog not used** — Hardcoded versions instead of `libs.versions.toml`
- **Unnecessary dependencies** — Dependencies added but not used
- **Missing KMP source sets** — Declaring `androidMain` code that could be `commonMain`
