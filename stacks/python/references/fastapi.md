# FastAPI

Covers: FastAPI 0.122+ (`Annotated` dependencies, `lifespan`, Pydantic v2 only), pydantic-settings, SQLAlchemy 2.0/2.1 async, httpx, pytest-asyncio 1.x. Read together with the main Python skill; the repository's own conventions win.

## Build

### App and config
- Build the app in a `create_app()` factory with a `lifespan` context manager for startup/shutdown; never `@app.on_event` (deprecated) — because when `lifespan` is set, `on_event` handlers are silently not called.
- Create shared clients (DB engine, `httpx.AsyncClient`, Redis) once in `lifespan` and close them on shutdown; never per request — because per-request clients throw away connection pools.
- Load settings with pydantic-settings `BaseSettings`; secrets are required fields with no default, typed `SecretStr`; expose settings through an `@lru_cache` `get_settings()` dependency so tests can override it.
- Manage schema with Alembic migrations; never run `Base.metadata.create_all()` on production startup.
- Keep routers HTTP-only (parse, call a service, map errors); business logic and transactions live in services, which raise domain exceptions, never `HTTPException`.

### Routes
- Use `async def` only when every I/O call inside is awaited; a handler that calls blocking code must be plain `def` (FastAPI runs it in a threadpool) — because one blocking call in `async def` stalls every request on the worker.
- Declare `response_model` (or a return annotation) on every route and keep separate `XCreate`/`XUpdate`/`XResponse` schemas; never return ORM objects or input schemas unfiltered — because the response model is what keeps `hashed_password` and internal fields out.
- Never set `ORJSONResponse`/`UJSONResponse` (deprecated in 0.131); let the response model or return type drive serialization — because since 0.130 Pydantic serializes it directly and faster.
- Set `status_code` explicitly (201 on create, 204 with no body on delete).
- Map domain exceptions to responses with `app.exception_handler`; never put stack traces, SQL or internal identifiers in `detail`.
- Constrain params (`Annotated[int, Query(ge=1, le=100)]`); list endpoints paginate with a bounded `limit` and a deterministic `order_by` — because offset pagination without ordering skips and repeats rows.
- Attach auth at the router (`APIRouter(dependencies=[Depends(require_user)])`) rather than route by route, so a new route cannot ship unauthenticated by omission.
- Use `BackgroundTasks` only for short, loss-tolerant work; durable jobs go to a queue — because background tasks die with the process. Never hand a request-scoped DB session to a background task; open a new one inside it.

### Pydantic v2
- Use v2 APIs: `model_config = ConfigDict(from_attributes=True)`, `model_validate`, `model_dump`, `field_validator`, `model_validator`; never v1 `class Config`, `orm_mode`, `.dict()`, `.parse_obj()`, `@validator` or `pydantic.v1` imports (unsupported since FastAPI 0.128).
- Apply PATCH with `payload.model_dump(exclude_unset=True)` — because omitted fields would otherwise overwrite stored values with `None`.
- Input schemas never contain server-controlled fields (`id`, `owner_id`, `role`, `is_admin`, `is_active`).
- Bound every input string and list (`Field(max_length=...)`); use `EmailStr`, enums and `Literal` for constrained values.

### Dependencies and database
- Provide the session from a `yield` dependency that rolls back on error and always closes; never create engines or sessions inside handlers.
- Commit in the service before returning, or declare `Depends(get_db, scope="function")` (0.121+) on a dependency that commits — because by default code after `yield` runs after the response is sent, so a failed commit still returns 2xx.
- Create sessions with `async_sessionmaker(engine, expire_on_commit=False)` and eager-load relationships (`selectinload`) — because lazy loads in async code raise `MissingGreenlet`.
- Install `sqlalchemy[asyncio]` on SQLAlchemy 2.1 — because greenlet is no longer a default dependency and async engines fail without it.
- Rely on DB unique constraints and catch `IntegrityError` (roll back, raise a domain error) instead of check-then-insert — because the precheck races.
- Use SQLAlchemy 2.0 style (`select()`, `session.execute()`, `.scalars()`); never interpolate values into `text()`.

### Auth and security
- Decode JWTs with PyJWT and a pinned algorithm (`jwt.decode(token, key, algorithms=[ALG])`), a verified signature and `exp`; treat a missing or malformed `sub` as 401; never decode with verification disabled.
- Return 401 (with `WWW-Authenticate`) when unauthenticated and 403 when authenticated but not allowed (the built-in security classes return 401 from 0.122, 403 before); check ownership on every object route.
- Hash passwords with argon2 or bcrypt (e.g. `pwdlib`); never store them in plain form or return them.
- Take CORS origins from settings as an explicit list; never `allow_origins=["*"]` with `allow_credentials=True`.
- Rate-limit login, registration and token endpoints.
- Set explicit timeouts on outbound clients (`httpx.AsyncClient(timeout=...)`).

## Test

- Test async apps with `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`; sync tests may use `TestClient`. `ASGITransport` does not run `lifespan` — use `asgi-lifespan`'s `LifespanManager` or `with TestClient(app)` when startup state matters.
- Override dependencies on a fresh app per test and clear them in teardown — because `dependency_overrides` is global app state:
  ```python
  @pytest_asyncio.fixture
  async def client(db_session):
      app = create_app()
      app.dependency_overrides[get_db] = lambda: db_session  # key: the callable inside Depends()
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
          yield c
      app.dependency_overrides.clear()
  ```
- The override key must be the exact callable passed to `Depends(...)`, not an `Annotated` alias, a wrapper or a re-imported copy.
- Isolate DB state per test (transaction rollback or fresh schema); use the production engine (e.g. Postgres in a container) when code relies on dialect features — SQLite with aiosqlite only for portable SQL.
- Keep async engine fixtures and tests on the same event-loop scope (pytest-asyncio `loop_scope`; never an `event_loop` fixture, removed in 1.0) — mismatches fail with "attached to a different loop".
- Every route gets: success, 422 on an invalid payload, 401 without credentials (0.122+), 403/404 on another user's resource, 404 on a missing one.
- Send JSON bodies with `json=` — because since 0.132 FastAPI rejects JSON without a JSON `Content-Type`; turning off `strict_content_type` needs a comment saying why.
- Test an explicit `null` separately from an omitted field — because since 0.151 `null` for a non-nullable field is a 422 even when the field has a default.
- Assert sensitive fields are absent from responses (`"hashed_password" not in resp.json()`).
- Override `get_current_user` for most tests, but keep real-token tests covering expired, tampered and wrong-algorithm tokens.
- Mock outbound HTTP with `respx` or a fake client injected through a dependency override; no real network.

## Review
Every Build and Test rule above is also a review check.

## Verify

Prefer the repository's own scripts and CI commands. Otherwise:

```bash
ruff format --check . && ruff check .
mypy .                     # enable the pydantic.mypy plugin
pytest -q                  # pytest-asyncio or anyio; add --cov=<package>
alembic check              # ORM models vs migrations drift (Alembic 1.9+)
pip-audit
```

- Build the OpenAPI schema in a test (`app.openapi()`) — it fails on schema errors that individual requests may never hit.
- Search the diff for `requests.`, `time.sleep(` and sync `Session` used inside `async def` handlers.
