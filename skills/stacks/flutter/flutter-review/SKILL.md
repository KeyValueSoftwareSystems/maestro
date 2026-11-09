---
name: flutter-review
description: Flutter and Dart review checklist — what to check in Flutter and Dart code, by severity. A reference for writing and reviewing it; in a workflow run the review step records each problem as a finding and the engine decides what blocks.
allowed-tools: Read, Grep, Glob, Bash
tags: [stack:flutter, review]
---

# Flutter and Dart review checklist

Use this when writing or reviewing Flutter and Dart code. The severities say how serious a problem is; they are guidance for a finding's severity, not a verdict.

## Review Checklist

### Architecture (CRITICAL)

Adapt to the project's chosen architecture (Clean Architecture, MVVM, feature-first, etc.):

- **Business logic in widgets** — Complex logic belongs in a state management component, not in `build()` or callbacks
- **Data models leaking across layers** — If the project separates DTOs and domain entities, they must be mapped at boundaries; if models are shared, review for consistency
- **Cross-layer imports** — Imports must respect the project's layer boundaries; inner layers must not depend on outer layers
- **Framework leaking into pure-Dart layers** — If the project has a domain/model layer intended to be framework-free, it must not import Flutter or platform code
- **Circular dependencies** — Package A depends on B and B depends on A
- **Private `src/` imports across packages** — Importing `package:other/src/internal.dart` breaks Dart package encapsulation
- **Direct instantiation in business logic** — State managers should receive dependencies via injection, not construct them internally
- **Missing abstractions at layer boundaries** — Concrete classes imported across layers instead of depending on interfaces

### State Management (CRITICAL)

**Universal (all solutions):**
- **Boolean flag soup** — `isLoading`/`isError`/`hasData` as separate fields allows impossible states; use sealed types, union variants, or the solution's built-in async state type
- **Non-exhaustive state handling** — All state variants must be handled exhaustively; unhandled variants silently break
- **Single responsibility violated** — Avoid "god" managers handling unrelated concerns
- **Direct API/DB calls from widgets** — Data access should go through a service/repository layer
- **Subscribing in `build()`** — Never call `.listen()` inside build methods; use declarative builders
- **Stream/subscription leaks** — All manual subscriptions must be cancelled in `dispose()`/`close()`
- **Missing error/loading states** — Every async operation must model loading, success, and error distinctly

**Immutable-state solutions (BLoC, Riverpod, Redux):**
- **Mutable state** — State must be immutable; create new instances via `copyWith`, never mutate in-place
- **Missing value equality** — State classes must implement `==`/`hashCode` so the framework detects changes

**Reactive-mutation solutions (MobX, GetX, Signals):**
- **Mutations outside reactivity API** — State must only change through `@action`, `.value`, `.obs`, etc.; direct mutation bypasses tracking
- **Missing computed state** — Derivable values should use the solution's computed mechanism, not be stored redundantly

**Cross-component dependencies:**
- In **Riverpod**, `ref.watch` between providers is expected — flag only circular or tangled chains
- In **BLoC**, blocs should not directly depend on other blocs — prefer shared repositories
- In other solutions, follow documented conventions for inter-component communication

### Widget Composition (HIGH)

- **Oversized `build()`** — Exceeding ~80 lines; extract subtrees to separate widget classes
- **`_build*()` helper methods** — Private methods returning widgets prevent framework optimizations; extract to classes
- **Missing `const` constructors** — Widgets with all-final fields must declare `const` to prevent unnecessary rebuilds
- **Object allocation in parameters** — Inline `TextStyle(...)` without `const` causes rebuilds
- **`StatefulWidget` overuse** — Prefer `StatelessWidget` when no mutable local state is needed
- **Missing `key` in list items** — `ListView.builder` items without stable `ValueKey` cause state bugs
- **Hardcoded colors/text styles** — Use `Theme.of(context).colorScheme`/`textTheme`; hardcoded styles break dark mode
- **Hardcoded spacing** — Prefer design tokens or named constants over magic numbers

### Performance (HIGH)

- **Unnecessary rebuilds** — State consumers wrapping too much tree; scope narrow and use selectors
- **Expensive work in `build()`** — Sorting, filtering, regex, or I/O in build; compute in the state layer
- **`MediaQuery.of(context)` overuse** — Use specific accessors (`MediaQuery.sizeOf(context)`)
- **Concrete list constructors for large data** — Use `ListView.builder`/`GridView.builder` for lazy construction
- **Missing image optimization** — No caching, no `cacheWidth`/`cacheHeight`, full-res thumbnails
- **`Opacity` in animations** — Use `AnimatedOpacity` or `FadeTransition`
- **Missing `const` propagation** — `const` widgets stop rebuild propagation; use wherever possible
- **`IntrinsicHeight`/`IntrinsicWidth` overuse** — Cause extra layout passes; avoid in scrollable lists
- **`RepaintBoundary` missing** — Complex independently-repainting subtrees should be wrapped

### Dart Idioms (MEDIUM)

- **Missing type annotations / implicit `dynamic`** — Enable `strict-casts`, `strict-inference`, `strict-raw-types` to catch these
- **`!` bang overuse** — Prefer `?.`, `??`, `case var v?`, or `requireNotNull`
- **Broad exception catching** — `catch (e)` without `on` clause; specify exception types
- **Catching `Error` subtypes** — `Error` indicates bugs, not recoverable conditions
- **`var` where `final` works** — Prefer `final` for locals, `const` for compile-time constants
- **Relative imports** — Use `package:` imports for consistency
- **Missing Dart 3 patterns** — Prefer switch expressions and `if-case` over verbose `is` checks
- **`print()` in production** — Use `dart:developer` `log()` or the project's logging package
- **`late` overuse** — Prefer nullable types or constructor initialization
- **Ignoring `Future` return values** — Use `await` or mark with `unawaited()`
- **Unused `async`** — Functions marked `async` that never `await` add unnecessary overhead
- **Mutable collections exposed** — Public APIs should return unmodifiable views
- **String concatenation in loops** — Use `StringBuffer` for iterative building
- **Mutable fields in `const` classes** — Fields in `const` constructor classes must be final

### Resource Lifecycle (HIGH)

- **Missing `dispose()`** — Every resource from `initState()` (controllers, subscriptions, timers) must be disposed
- **`BuildContext` used after `await`** — Check `context.mounted` (Flutter 3.7+) before navigation/dialogs after async gaps
- **`setState` after `dispose`** — Async callbacks must check `mounted` before calling `setState`
- **`BuildContext` stored in long-lived objects** — Never store context in singletons or static fields
- **Unclosed `StreamController`** / **`Timer` not cancelled** — Must be cleaned up in `dispose()`
- **Duplicated lifecycle logic** — Identical init/dispose blocks should be extracted to reusable patterns

### Error Handling (HIGH)

- **Missing global error capture** — Both `FlutterError.onError` and `PlatformDispatcher.instance.onError` must be set
- **No error reporting service** — Crashlytics/Sentry or equivalent should be integrated with non-fatal reporting
- **Missing state management error observer** — Wire errors to reporting (BlocObserver, ProviderObserver, etc.)
- **Red screen in production** — `ErrorWidget.builder` not customized for release mode
- **Raw exceptions reaching UI** — Map to user-friendly, localized messages before presentation layer

### Testing (HIGH)

- **Missing unit tests** — State manager changes must have corresponding tests
- **Missing widget tests** — New/changed widgets should have widget tests
- **Missing golden tests** — Design-critical components should have pixel-perfect regression tests
- **Untested state transitions** — All paths (loading→success, loading→error, retry, empty) must be tested
- **Test isolation violated** — External dependencies must be mocked; no shared mutable state between tests
- **Flaky async tests** — Use `pumpAndSettle` or explicit `pump(Duration)`, not timing assumptions

### Accessibility (MEDIUM)

- **Missing semantic labels** — Images without `semanticLabel`, icons without `tooltip`
- **Small tap targets** — Interactive elements below 48x48 pixels
- **Color-only indicators** — Color alone conveying meaning without icon/text alternative
- **Missing `ExcludeSemantics`/`MergeSemantics`** — Decorative elements and related widget groups need proper semantics
- **Text scaling ignored** — Hardcoded sizes that don't respect system accessibility settings

### Platform, Responsive & Navigation (MEDIUM)

- **Missing `SafeArea`** — Content obscured by notches/status bars
- **Broken back navigation** — Android back button or iOS swipe-to-go-back not working as expected
- **Missing platform permissions** — Required permissions not declared in `AndroidManifest.xml` or `Info.plist`
- **No responsive layout** — Fixed layouts that break on tablets/desktops/landscape
- **Text overflow** — Unbounded text without `Flexible`/`Expanded`/`FittedBox`
- **Mixed navigation patterns** — `Navigator.push` mixed with declarative router; pick one
- **Hardcoded route paths** — Use constants, enums, or generated routes
- **Missing deep link validation** — URLs not sanitized before navigation
- **Missing auth guards** — Protected routes accessible without redirect

### Internationalization (MEDIUM)

- **Hardcoded user-facing strings** — All visible text must use a localization system
- **String concatenation for localized text** — Use parameterized messages
- **Locale-unaware formatting** — Dates, numbers, currencies must use locale-aware formatters

### Dependencies & Build (LOW)

- **No strict static analysis** — Project should have strict `analysis_options.yaml`
- **Stale/unused dependencies** — Run `flutter pub outdated`; remove unused packages
- **Dependency overrides in production** — Only with comment linking to tracking issue
- **Unjustified lint suppressions** — `// ignore:` without explanatory comment
- **Hardcoded path deps in monorepo** — Use workspace resolution, not `path: ../../`

### Security (CRITICAL)

- **Hardcoded secrets** — API keys, tokens, or credentials in Dart source
- **Insecure storage** — Sensitive data in plaintext instead of Keychain/EncryptedSharedPreferences
- **Cleartext traffic** — HTTP without HTTPS; missing network security config
- **Sensitive logging** — Tokens, PII, or credentials in `print()`/`debugPrint()`
- **Missing input validation** — User input passed to APIs/navigation without sanitization
- **Unsafe deep links** — Handlers that act without validation
