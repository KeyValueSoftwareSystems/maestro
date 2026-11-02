# Project configuration: `maestro.config.yaml`

One file at the workspace root records how this project is built, tested and delivered.
Engine steps read it, so verification runs the project's real commands instead of an agent's
guess. `maestro init` writes it; edit it by hand whenever a command changes. The golden
workflow never changes per project — it reads these values.

```yaml
version: 1
repos:                          # one entry per repository Maestro finds
  backend:
    stack: go                   # optional; selects the matching stack skills
    commands:                   # shell commands, run inside the repo (or its worktree)
      setup: make deps          # optional
      build: make build         # required
      typecheck: ""             # optional; empty means not available
      lint: golangci-lint run   # recommended
      test: go test ./...       # required
      e2e: make e2e             # recommended; used by QA
    timeout_s: 900              # optional, per command (default 900)
  web:
    stack: react
    commands:
      build: npm run build
      lint: npm run lint
      test: npm test -- --watchAll=false
environment:                    # optional: bring the stack up for QA
  start: docker compose up -d
  stop: docker compose down
delivery:                       # optional
  mode: branch                  # branch | pull-request
  base: main
```

Repository names are the ones Maestro discovers: each git repo under `codebase/`, or the
workspace root itself in a single-repo layout.

## Check it

```bash
python3 .maestro/engine/maestroctl.py preflight
```

| Finding | Level |
|---|---|
| File missing or unreadable | error |
| A repository has no entry under `repos` | error |
| A repository has no `build` or `test` command | error |
| Unknown key inside `repos`, `commands`, `environment` or `delivery` (a typo) | error |
| No `lint` or `e2e` command | warning — that check is skipped |
| A configured repository is not in the workspace | warning |

Issues print to stderr; a JSON summary prints to stdout. The exit code is 1 when there is any
error. Top-level keys other than the ones above are allowed: a workflow can read its own values
with `${config.<path>}`.
