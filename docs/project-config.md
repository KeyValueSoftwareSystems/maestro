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
    role: app                   # optional; app | infra (an infrastructure repository)
    commands:                   # shell commands, run inside the repo (or its worktree)
      setup: make deps          # optional
      build: make build         # required
      typecheck: ""             # optional; empty means not available
      lint: golangci-lint run   # recommended
      test: go test ./...       # required
      e2e: make e2e             # recommended; used by QA
    timeout_s: 900              # optional, per command (default 900)
    test_patterns: ["tests/*"]  # optional; which files are tests (default: common conventions)
  web:
    stack: react
    commands:
      build: npm run build
      lint: npm run lint
      test: npm test -- --watchAll=false
environment:                    # optional: bring the stack up for QA
  start: docker compose up -d --build
  ready: ./scripts/wait-for-health   # optional; QA starts only after it passes
  stop: docker compose down
infrastructure:                 # optional; overrides the detected level for HLD questions
  level: iac                    # none | containers | iac
delivery:                       # optional; what happens after release approval
  mode: branch                  # branch (report the verified branches) | pull-request
  base: main                    # pull-request base (default: the remote's default branch)
  remote: origin                # where branches are pushed (default origin)
```

Repository names are the ones Maestro discovers: each git repo under `codebase/`, or the
workspace root itself in a single-repo layout.

QA runs against the code the engine verified, not the main checkouts. The engine runs
`environment.start` (then `ready`) before QA and `stop` after it, at the workspace root, with the
code under test in environment variables: `MAESTRO_SLUG`, `MAESTRO_MANIFEST`, and per repository
`MAESTRO_WORKTREE_<REPO>` and `MAESTRO_COMMIT_<REPO>` (name upper-cased, other characters as `_`)
— point your compose build contexts or start scripts at them. After the QA agent's suite passes,
the engine runs each repository's `e2e` command in its worktree (same variables) and writes
`qa/e2e-receipt.json`; a failure goes back to the QA fixer. Without `e2e`, QA results are only
what the QA agent reports.

After release approval, `delivery.mode: pull-request` pushes each repository's verified branch
(never forced; refused if the branch moved off its verified commit) and opens a pull request with
the GitHub CLI (`gh`, installed and logged in), or reuses the open one. The body carries that
repository's verification result, the acceptance-criteria trace, the assumptions summary, links
to the sibling pull requests and the review pack. A release approved on autopilot opens drafts.
Results land in `.maestro/runs/<slug>/delivery.json`. `branch` (the default) pushes nothing.

The verify step runs these commands in each implementation worktree and writes a receipt. It
also lists existing test files the branch modified, renamed or deleted (matched by
`test_patterns`); the code reviewer must justify each one. New test files are not listed.

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
