# Django

Covers: Django 5.2 LTS, 6.0 and 6.1 (6.x needs Python 3.12+), Django REST Framework 3.16+ (3.17+ on Django 6), Celery 5.5+, pytest-django, factory_boy. Read together with the main Python skill; the repository's own conventions win.

## Build

### Settings
- Split settings (`base`/`dev`/`test`/`prod`); read `SECRET_KEY`, DB credentials and `ALLOWED_HOSTS` from the environment and fail at startup if `SECRET_KEY` is missing — never commit a fallback key.
- Production settings set `DEBUG = False`, explicit `ALLOWED_HOSTS`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS` and `CSRF_TRUSTED_ORIGINS`; confirm with `check --deploy`.
- Reference the user model as `settings.AUTH_USER_MODEL` in FKs and `get_user_model()` in code; never import `django.contrib.auth.models.User` directly.
- Keep `AUTH_PASSWORD_VALIDATORS` on; a fast (MD5) password hasher belongs only in test settings.
- Set `DEFAULT_AUTO_FIELD` explicitly; never accept an upgrade migration that alters every `id` to `BigAutoField` — because 6.0 changed the default.
- In server-rendered apps add `LoginRequiredMiddleware` (5.1+) and mark public views `@login_not_required` — so a new view cannot ship unauthenticated by omission.
- On 6.0+, set `SECURE_CSP` with `ContentSecurityPolicyMiddleware` for apps that serve HTML; start with `SECURE_CSP_REPORT_ONLY` while inline scripts remain.

### Models
- Every FK/M2M has an explicit `related_name`; choose `on_delete` deliberately (`PROTECT` for financial/audit rows, not reflexive `CASCADE`).
- Use `on_delete=DB_CASCADE`/`DB_SET_NULL` (6.1+) only when no `pre_delete`/`post_delete` receiver or Python-side cascade must run — because the database deletes the rows and signals never fire.
- Index fields used in `filter()`/`order_by()` (`db_index=True` or `Meta.indexes`, composite for multi-column filters); FKs are indexed already.
- Enforce invariants with `UniqueConstraint`/`CheckConstraint` — because `clean()` is skipped by `save()`, `update()` and `bulk_create()`. Use `CheckConstraint(condition=...)`; `check=` was removed in 6.0.
- Container defaults are callables: `default=list`/`dict`, never `default=[]`/`{}`.
- `null=True` only on non-string fields (paired with `blank=True` when optional); optional string fields use `blank=True` and store `""`.
- Store money in `DecimalField`; expose reusable filters as custom `QuerySet` methods via `as_manager()`.

### ORM
- Add `select_related` (FK/one-to-one) or `prefetch_related` (reverse FK/M2M) to any queryset whose relations are read in a loop, serializer or template.
- Use `.exists()` for existence and `.count()` for counts; never `if qs:` or `len(qs)` — both fetch every row.
- Save partial changes with `save(update_fields=[...])` (keywords only; positional `save()` arguments were removed in 6.0); change counters with `F()` (`stock=F("stock") - 1`) or `select_for_update()` inside `atomic()` — because read-modify-write loses concurrent updates.
- Wrap every multi-write operation in `transaction.atomic()`.
- Run side effects (emails, task enqueues, webhooks) in `transaction.on_commit(...)` — because otherwise they fire for rolled-back writes, or a worker reads the row before it is committed.
- `bulk_create`/`bulk_update`/`update()` skip `save()` and signals; handle duplicates explicitly (`update_conflicts=True` with `unique_fields`/`update_fields`, or `ignore_conflicts=True`).
- Handle `DoesNotExist` on every `.get()` (`get_object_or_404` in views).
- Raw SQL only with parameters: `.raw("... WHERE id = %s", [pk])`, `cursor.execute(sql, params)`; never f-strings or `%` formatting; avoid `.extra()`.

### Structure
- Business logic lives in service/domain modules; views, serializers and admin stay thin.
- Prefer explicit service calls to signals; if a signal is needed, connect it in `AppConfig.ready()`.
- Never cache user-specific responses under a shared key (e.g. `cache_page` on authenticated views); version or invalidate cache keys on write.
- Call slow external APIs from Celery, not inside the request.
- With `django.tasks` (6.0+), configure a production backend and worker — the built-in backends are for development and tests only — and enqueue in `transaction.on_commit`, as with Celery.

### Migrations
- Every model change ships with its migration; read the generated file before committing it.
- Drop or rename a column in two deploys (stop using it and make it nullable, then remove it) — because old code runs against the new schema during rollout.
- Add a NOT NULL column to a populated table as nullable or with `db_default` (5.0+), backfill, then tighten.
- `RunPython` always has `reverse_code` (`migrations.RunPython.noop` if nothing to undo) and uses `apps.get_model()` — because imported models do not match the historical schema.
- Set `atomic = False` only with a comment saying why (e.g. Postgres `AddIndexConcurrently`).
- Never edit a migration that has been applied anywhere shared; add a new one.

### Security
- Templates auto-escape; never `|safe` or `mark_safe()` on user input — build HTML with `format_html()`.
- Use `@csrf_exempt` only on webhooks that verify a signature.
- Never splat request data into ORM keyword arguments (`filter(**request.GET.dict())`, `Q(**params)`, `annotate(**{name: ...})`) or pass it to `order_by()`; map an allow-list of field names — because keys become lookups, aliases or internal options such as `_connector` (SQL injection, CVE-2025-64459).
- Scope object querysets to the requester (`get_queryset()` filters by owner/tenant) so other users' IDs return 404.
- Validate uploads: size limit, content type from magic bytes matching the extension, server-generated filename, storage outside the app's static root.
- Admin: never show secrets or password hashes in `list_display` or editable fields; put auto-generated data in `readonly_fields`.

### DRF
- Every `ModelSerializer` lists `fields = [...]` explicitly; never `"__all__"` or `exclude` — because new columns then leak automatically.
- Set `read_only_fields` for ids, timestamps and ownership fields; password fields are `write_only=True`.
- Inject server-side values (owner, tenant) in `perform_create`/`perform_update` via `serializer.save(owner=self.request.user)`; never take them from the payload or set them in `validate()`.
- Every view states `permission_classes`, or the global default is `IsAuthenticated`. Object permissions run only through `get_object()`, so list views and custom lookups must filter the queryset themselves.
- Every list endpoint paginates (`DEFAULT_PAGINATION_CLASS` + `PAGE_SIZE`, or per view).
- Throttle login, registration, password-reset and OTP endpoints.
- Writable nested serializers implement `create()`/`update()` for the nested data inside `atomic()`.
- Give the viewset `queryset` the `select_related`/`prefetch_related` its serializer needs; a `SerializerMethodField` that queries per row is an N+1.
- In serializers read the user from `self.context["request"]`.

### Celery
- Pass primary keys and JSON-serializable primitives as task args; never model instances — because they are stale by execution time.
- Make tasks idempotent with a guarded state transition — because `acks_late` and retries redeliver:
  ```python
  updated = Order.objects.filter(pk=order_id, status=Status.PROCESSING).update(
      status=Status.SHIPPED, tracking=tracking)
  if not updated:
      return  # already shipped or gone
  ```
- Enqueue from request code with `transaction.on_commit(lambda: task.delay(obj.pk))`.
- Retry only transient errors: `autoretry_for=(ConnectionError, TimeoutError)`, `retry_backoff=True`, `retry_jitter=True`, bounded `max_retries`; after the last retry record the failure (dead-letter row or alert) instead of dropping it.
- Set `soft_time_limit` and `time_limit`; catch `SoftTimeLimitExceeded` only to clean up, then re-raise.
- Use the JSON serializer only (never pickle), `task_acks_late=True` with `worker_prefetch_multiplier=1` for long tasks, and an explicit, stable task `name=`.
- Never call `.get()` on a result inside a task or request, or `.apply()` in a view — both block.
- Run beat on exactly one node — because two schedulers enqueue every periodic task twice.

## Test

- Mark DB tests `@pytest.mark.django_db` (or request the `db` fixture); use `transaction=True` only when testing real transaction behavior.
- Test `on_commit` side effects with `django_capture_on_commit_callbacks(execute=True)` (or `TestCase.captureOnCommitCallbacks`) — because the test transaction never commits.
- Build data with factory_boy (`Sequence` for unique fields, `SubFactory` for FKs); never hand-built object graphs with hardcoded IDs.
- Test settings: fast password hasher, locmem email (assert on `mail.outbox`), `CELERY_TASK_ALWAYS_EAGER = True` and `CELERY_TASK_EAGER_PROPAGATES = True` for integration tests.
- Run tests on the production DB engine when code uses backend-specific features (JSON lookups, `select_for_update`, constraints, full-text search); SQLite hides those bugs.
- `--reuse-db` is fine; use `--nomigrations` only if another CI job applies migrations — because it hides broken migrations.
- Every endpoint gets: anonymous → 401/403, another user's object → 404/403, permitted user → success, invalid payload → 400 naming the field.
- Keep at least one test per auth scheme that logs in through the real path; `force_authenticate`/`force_login` is fine elsewhere.
- Pin query counts on list/detail endpoints with `django_assert_num_queries` to catch N+1 regressions.
- Change settings with the `settings` fixture or `override_settings`, never by assigning to `django.conf.settings`.
- Celery: call the task function directly in unit tests; run it twice to prove idempotency; exercise retry paths with `task.apply(args=[...], throw=True)`.
- Mock external services at the module that imports them (the service), not at the view.

## Review
Every Build and Test rule above is also a review check. Also check for a queryset reused after `.delete()`.

## Verify

Prefer the repository's own scripts and CI commands. Otherwise:

```bash
python manage.py check                              # add --deploy with production settings
python manage.py makemigrations --check --dry-run   # model changes without migrations
python manage.py migrate --plan                     # review order and irreversible ops
pytest --reuse-db -q                                # pytest-django; add --cov=<package>
ruff check . && mypy .                              # mypy with django-stubs / djangorestframework-stubs
bandit -r . -ll && pip-audit
```

- With drf-spectacular, `python manage.py spectacular --validate --fail-on-warn` catches broken API schemas.
- Confirm `django` is on a supported release series at its latest patch — check the Django download page, because Django ships security releases often.
- Before finishing, search the diff for `print(`, `breakpoint()`, `import pdb` and `DEBUG = True`, and confirm a migration accompanies every model change.
