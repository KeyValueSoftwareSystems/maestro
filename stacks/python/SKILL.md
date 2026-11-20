---
name: python
description: Rules for writing, testing and reviewing Python 3.11+ code (typing, error handling, async, security, pytest), with a severity-graded review checklist. Django (with DRF and Celery) and FastAPI are covered in reference files, and it applies whenever a Python change is being built, tested or reviewed.
---
# Python

Covers: Python 3.11–3.15 (newer features are flagged; 3.10 is end of life), pytest 8.4/9, Ruff, mypy 2.x or pyright, uv. If the repository's own conventions (its AGENTS.md/CLAUDE.md, lint config, existing code) disagree with this skill, follow the repository.

## Build

### Types
- Annotate every function signature in new or changed code, including `-> None` — because mypy skips the bodies of unannotated functions by default.
- Use `list[str]`, `dict[str, int]`, `X | None`; never `typing.List`/`Dict`/`Optional`/`Union` in new code.
- Never use `Any` where a `Protocol`, `TypeVar` or `object` fits — because `Any` silently switches off checking for everything it touches.
- Use `Enum`/`StrEnum` or `Literal[...]` for closed sets of values; never compare against bare magic strings or numbers.
- Use `typing.Self` for methods returning their own class; mark overrides with `@override` (3.12+, `typing_extensions` before).
- Never write a bare `# type: ignore`; scope it to an error code (`# type: ignore[attr-defined]`) and say why.
- Use syntax only at or above the repo's `requires-python` floor: unparenthesized `except A, B:` and t-strings need 3.14, `lazy import` needs 3.15 — because older interpreters fail at import.

### Data and state
- Never use mutable or call-evaluated default arguments (`def f(x=[])`, `def f(ts=datetime.now())`) — because defaults are evaluated once, at definition time; default to `None`.
- Use `@dataclass(frozen=True, slots=True)` for value objects and `field(default_factory=list)` for container fields.
- Validate untrusted input at the boundary (Pydantic v2 or explicit parsing) and pass typed objects inward, not raw `dict`s.
- Use `Decimal` built from `str` for money; never `float`.
- Use aware datetimes (`datetime.now(UTC)`); never `datetime.utcnow()`/`utcfromtimestamp()` (deprecated since 3.12, return naive values). Use `time.monotonic()` for durations.
- Pass `encoding="utf-8"` to text-mode `open()`/`read_text()` while the repo supports Python < 3.15 — because before 3.15 the default is the locale encoding.

### Errors and resources
- Catch the narrowest exception the `try` body can raise, and keep the `try` body to the statements that raise it — because broad blocks mask unrelated bugs.
- Never write bare `except:` or `except Exception: pass`; a broad catch belongs only at a top-level boundary, with `logger.exception(...)` and a re-raise or explicit error result.
- Re-raise as a domain error with `raise AppError(...) from exc` so the cause survives; use `from None` only to hide a chain deliberately.
- Give the package a base exception (`class AppError(Exception)`) with specific subclasses; never signal failure by returning `None`/`False` where callers cannot tell it from a value.
- Never `return`, `break` or `continue` out of a `finally` block — because it silently discards the in-flight exception (a `SyntaxWarning` since 3.14).
- Manage files, locks, connections and sessions with `with`/`async with`; never rely on `__del__` or garbage collection to close them.

### Logging and modules
- Use `logger = logging.getLogger(__name__)`; never `print()` outside CLI output; never call `logging.basicConfig()` from library code.
- Pass log arguments lazily (`logger.info("user %s", uid)`), not f-strings — because formatting runs even when the level is off and breaks log grouping.
- Never log secrets, tokens, passwords or full request/response bodies.
- Do no work at import time (network, DB, env read into module constants tests cannot override); build clients in a factory or on first use.

### Concurrency
- Never call blocking I/O (`requests`, `time.sleep`, sync DB drivers, `subprocess.run`) inside `async def`; use an async client or `await asyncio.to_thread(...)`.
- Prefer `asyncio.TaskGroup` to bare `create_task`; if you call `create_task`, keep a reference — because the loop holds tasks weakly and can drop them mid-flight.
- Never call `asyncio.get_event_loop()` or set event-loop policies; use `asyncio.run()`, `asyncio.Runner(loop_factory=...)` and `asyncio.get_running_loop()` — because 3.14 raises `RuntimeError` when no loop is running and deprecates policies for removal.
- Put a timeout on every network call (`httpx` timeout, `asyncio.timeout()`); `requests` has no default timeout and can hang forever.
- Guard mutable state shared between threads with a `Lock`.
- Pass process-pool work as picklable arguments; never rely on globals inherited through `fork` (request `get_context("fork")` explicitly if you must) — because 3.14 made `forkserver` the default start method on Linux.
- Never issue one query or HTTP call per item in a loop when a batch call exists (N+1).

### Security
- Parameterize SQL (`cursor.execute(sql, params)`, SQLAlchemy `text()` with bound params); never build SQL with f-strings, `%` or `.format`.
- Run commands with `subprocess.run([...], check=True)` and list args; never `shell=True` with interpolated input, never `os.system`.
- Never `eval`/`exec`, or load `pickle`/`marshal`/`shelve`/`yaml.load` from untrusted data; use `json`, `yaml.safe_load`, and `defusedxml` for XML.
- Resolve user-supplied paths and check containment with `(base / name).resolve().is_relative_to(base.resolve())` — because `..` and absolute paths escape the base directory.
- Extract tar archives with `filter="data"` (the default from 3.14) on a patched interpreter (3.12.11+, 3.13.4+); never `filter="fully_trusted"` on untrusted input — because older patch releases let crafted links escape the filter (CVE-2025-4517).
- Use `secrets` for tokens, never `random`; use SHA-256 or stronger for integrity (never MD5/SHA-1) and argon2/bcrypt for passwords.
- Read secrets from the environment or a secret store; never hardcode them or ship a working default.
- Never disable TLS verification (`verify=False`).

### Dependencies
- Commit the lockfile (`uv.lock`, `poetry.lock` or `pylock.toml`) with every dependency change and install in CI with `uv sync --locked` — because an unlocked install resolves whatever was published that minute.
- Never reach internal packages through `--extra-index-url` or `index-strategy = "unsafe-best-match"`; pin them to an index marked `explicit = true` in `[tool.uv.sources]` — because mixed indexes allow dependency confusion.
- Unless the repo opts out, hold back new releases with a cooldown (`exclude-newer = "7 days"` in uv, `--uploaded-prior-to P7D` on pip 26.1+) — because it keeps a just-published, possibly hijacked release out of the lock.

## Test

- Use pytest with plain `assert`; add `unittest.TestCase` classes only if the repo already uses them.
- For a bug fix, add a test that fails without the fix. For a feature, cover the happy path, each error path and boundaries (empty, `None`, zero, max, non-ASCII).
- Test behavior through the public API; never assert on private attributes or call `_private` helpers.
- Name tests `test_<unit>_<condition>_<expected>` (e.g. `test_withdraw_over_balance_raises`); name files `test_<module>.py`, mirroring the package layout.
- One behavior per test; no loops or `if` in test bodies — use `@pytest.mark.parametrize(..., ids=[...])` so each case reports separately.
- Wrap only the raising call in `pytest.raises(Err, match="...")`; never `try/except` plus `assert False`.
- Keep fixtures in the nearest `conftest.py`, function-scoped by default; widen to `module`/`session` only for expensive, immutable resources — because shared mutable fixtures cause order-dependent failures. Use `yield` fixtures for teardown; use `autouse` only for global isolation.
- Use built-ins: `tmp_path` for files, `monkeypatch` for env vars and attributes, `caplog` for log assertions; never write to the real home/cwd or mutate `os.environ` directly.
- Mock only boundaries you do not own (network, clock, randomness, third-party SDKs); never mock the unit under test. Prefer a small fake over deep `Mock` chains.
- Patch the name where it is looked up, not where it is defined:
  ```python
  # myapp/billing.py does: from myapp.gateway import charge
  with patch("myapp.billing.charge", autospec=True) as charge:   # correct
      ...
  # patch("myapp.gateway.charge") leaves billing calling the real function
  ```
- Create mocks with `autospec=True`/`create_autospec` so wrong signatures fail; use `AsyncMock` for coroutines and assert with `assert_awaited_once_with(...)`.
- Assert outcomes (return values, persisted state, calls with their arguments), not just `assert_called()`.
- No real network, no `sleep`, no wall-clock dependence: freeze time (`time-machine`/`freezegun`) or inject a clock, and seed randomness.
- Set `strict = true` in `[tool.pytest]` (pytest 9+; `--strict-markers` on 8.x) — because it also turns on `strict_config`, `strict_xfail` and `strict_parametrization_ids`, so a typo cannot silently deselect or pass a test.
- For async tests use pytest-asyncio 1.x (`asyncio_mode = "auto"` or `@pytest.mark.asyncio`, scoped with `loop_scope`; never an `event_loop` fixture, removed in 1.0) or anyio, matching the repo — pytest 8.4+ fails async tests that no plugin runs.
- Tests must pass in any order and in parallel (`pytest -p randomly`, `pytest -n auto`).
- Cover every changed branch, including error paths; meet the repo's coverage gate (default 80%+, critical paths fully); never add assertion-free tests to raise the number.

## Review

Severity says how serious a problem is. Report each with its location and the fix.

### Critical — Security
- SQL built with f-strings, `%` or `.format` — parameterize.
- Unvalidated input in shell commands (`shell=True`, `os.system`) — use list args.
- User-controlled paths not resolved and contained under a base dir; tar extraction with `fully_trusted` or on an unpatched interpreter.
- `eval`/`exec` on input; unsafe deserialization (`pickle`, `marshal`, `yaml.load`) of untrusted data.
- Hardcoded secrets, tokens or passwords; secrets written to logs.
- Weak crypto for security (MD5/SHA-1, `random` for tokens); TLS verification disabled.
- Dependency changed without its lockfile; an extra index added for internal packages.

### Critical — Error handling
- Bare `except:` or `except Exception: pass`; exceptions swallowed or turned into silent `None` returns.
- `return`/`break`/`continue` inside `finally`.
- Files, locks or connections managed by hand instead of `with`.

### High — Type hints
- Public functions without annotations.
- `Any` where a specific type, `Protocol` or `TypeVar` fits.
- Nullable parameters not typed `X | None`; unscoped `# type: ignore`.

### High — Pythonic patterns
- Mutable or call-evaluated default arguments.
- Magic numbers or strings instead of named constants or `Enum`.

### High — Code quality
- Functions over ~50 lines or with more than 5 parameters (group into a dataclass).
- Nesting deeper than 4 levels.

### High — Concurrency
- Mutable state shared across threads without a lock.
- Blocking calls inside `async def`; un-awaited coroutines; `create_task` results dropped.
- `asyncio.get_event_loop()` or event-loop policies; process-pool code that relies on `fork`-inherited globals.
- Network calls without a timeout.
- N+1 queries or calls in loops — batch them.

### Medium — Best practices
- Public functions with non-obvious behavior and no docstring.
- `print()` instead of `logging`; f-strings in log calls.
- Naive datetimes, `datetime.utcnow()` or `utcfromtimestamp()`.

### Medium — Tests
- Changed behavior or bug fix with no test.
- Tests that hit the network, sleep, or depend on run order.
- Mocks without autospec, or tests that only assert a mock was called.

### Other frameworks
- Flask: missing error handlers; CSRF protection absent on form posts.
- Django and FastAPI: see References.

## Verify

Prefer the repository's own entry points (Makefile/justfile targets, `tox`/`nox` sessions, `pre-commit run --all-files`, the commands in its CI config) and run tools through its environment manager (`uv run`, `poetry run`, `hatch run`). Otherwise:

```bash
ruff format --check .            # or: black --check .
ruff check .
mypy .                           # or: pyright
pytest -q                        # add --cov=<package> --cov-report=term-missing
uv lock --check                  # uv projects: lockfile matches pyproject.toml
pip-audit                        # known-vulnerable dependencies
bandit -r <package> -ll          # only if the repo uses bandit instead of Ruff's S rules
```

- Unless the repo opts out, enable Ruff rules `I`, `B006`, `B008`, `ASYNC`, `DTZ`, `S`, `G004`, `T20` and `BLE001` — because they machine-check import order, mutable defaults, blocking calls in async code, naive datetimes, security issues, log formatting, `print` and blind excepts.
- Run the narrowest selection first (`pytest path/to/test_x.py -k name`), then the full suite before finishing.
- Never reach green by deleting or skipping tests, loosening assertions, or adding lint/type ignores; report any check you could not run or fix.

## References

- `references/django.md` — read when the change touches Django models, migrations, views, templates, settings, DRF serializers/viewsets/permissions, Celery tasks, or pytest-django tests.
- `references/fastapi.md` — read when the change touches FastAPI apps, routers, dependencies, Pydantic v2 schemas, async SQLAlchemy sessions, auth, or FastAPI tests.
