# Project configuration: `maestro.config.yaml`

One file at the workspace root records how this project is built, tested and delivered.
Engine steps read it, so verification runs the project's real commands instead of an agent's
guess. `/maestro-init` writes it through the project-config skill: repo names come from
`registry.yaml` when that file exists, and stack and commands come from the detect-stack
result. Running detect-stack alone does not write this file. Edit it by hand whenever a
command changes. The golden
workflow never changes per project — it reads these values.

```yaml
version: 1
repos:                          # one entry per repository Maestro finds
  backend:
    stack: go                   # optional; the installed stack:go skills are applied when this repo
                                # is implemented, reviewed and fixed ("go, db" for several)
    role: app                   # optional; app | infra (an infrastructure repository)
    commands:                   # shell commands, run inside the repo (or its worktree)
      setup: make deps          # optional
      build: make build         # required
      typecheck: ""             # optional; empty means not available
      lint: golangci-lint run   # recommended
      test: go test ./...       # required
      security: gosec ./...     # recommended; the project's own scanner (semgrep, npm audit…)
      e2e: make e2e             # recommended; used by QA
    timeout_s: 900              # optional, per command (default 900)
    test_patterns: ["tests/*"]  # optional; which files are tests (default: common conventions)
  infra:                        # an infrastructure repository is verified like any other
    stack: terraform
    role: infra
    commands:
      build: terraform fmt -check -recursive && terraform init -backend=false
      test: terraform validate
      security: tfsec .
  web:
    stack: react
    commands:
      build: npm run build
      lint: npm run lint
      test: npm test -- --watchAll=false
environment:                    # optional: bring the stack up for QA
  start: docker compose up -d --build
  ready: ./scripts/wait-for-health   # recommended; QA starts only after it passes (preflight warns without it)
  stop: docker compose down
infrastructure:                 # optional; overrides the detected level for HLD questions
  level: iac                    # none | containers | iac
design:                         # optional
  light_max_criteria: 5         # most acceptance criteria a light (no HLD) design may have (default 5)
reviews:                        # optional
  max_rounds: 3                 # reviews of one document or branch before a person decides (default 3)
delivery:                       # optional; what happens after release approval
  mode: branch                  # branch (report the verified branches) | pull-request
  base: main                    # pull-request base (default: the remote's default branch)
  remote: origin                # where branches are pushed (default origin)
worktree:                       # optional; how each feature's worktrees are made (default: below)
  create: ./scripts/sandbox create {slug} -y   # once per feature, from the workspace root
  path: sandbox/{slug}/codebase/{repo}         # where create leaves each repository
  branch: sandbox/{slug}                       # optional; the branch create checks out
  remove: ./scripts/sandbox rm {slug} -y       # optional; run after delivery
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

The engine creates each feature's worktrees before any agent writes code, once per feature
(`engine/worktrees.py`). Without a `worktree` section it runs `git worktree add` itself: one
worktree per selected repository at `.maestro/worktrees/<slug>/<repo>` (ignored by git), on
branch `feature/<slug>-<repo>`. With one, it runs `create` instead (for example the workspace
template's sandbox command; `/maestro-init` fills this section from that script's documented
usage) and finds each repository at `path`. `{slug}` and `{root}` in the commands are replaced
(shell-quoted) and `MAESTRO_SLUG` / `MAESTRO_ROOT` are exported; `path` and `branch` take `{slug}`
and `{repo}`. Point `environment.start` at the same sandbox (for example
`./scripts/infra up "$MAESTRO_SLUG"`) and QA builds the code Maestro wrote.

Maestro uses only worktrees it created. A path that already exists and is not in the run's
record (`.maestro/runs/<slug>/worktrees.json`) is refused, as is a new worktree that is not clean
or does not start at the commit the feature's workspace lock pinned. A resumed run or a later
delivery pass reuses its own. After delivery, the engine removes what it created: its own
worktrees with `git worktree remove` (the branches stay), a configured sandbox with `remove` only
when the delivery pushed every branch (`delivery.mode: pull-request`) — the remove command may
delete them. A worktree with uncommitted changes is always kept.

The verify step runs these commands in each implementation worktree and writes a receipt. It
also scans the lines the branch added for committed credentials (cloud keys, private keys,
provider tokens) and fails as `secrets` when it finds one, recording the file and line but never
the value. It fails as `build-output` when the branch adds build or tool output no repository
commits on purpose (`__pycache__/`, `*.pyc`, `node_modules/`, `.pytest_cache/`, `.DS_Store`,
`*.class`, …); `dist/` and `build/` are not on that list, since some projects commit them. Its
summary names the checks the project left unconfigured (for example "not configured: lint,
security"), so a pass is never read as a full check. It
also lists existing test files the branch modified, renamed or deleted (matched by
`test_patterns`); the code reviewer must justify each one. New test files are not listed.

A check that fails is run once more on the commit the branch started from, in an engine-owned
checkout under `.maestro/baseline/<repo>/` (ignored by git; `setup` runs there first). If it fails
there too, the receipt marks it `pre-existing` and it does not fail verification: an old lint
backlog or a broken build script no longer sends the fixer after problems the feature did not
cause. The result is cached per base commit and command, so a slow build runs on the base once.
Pre-existing **test** failures are different: the engine cannot show the feature's tests pass, so
the release verdict is `baseline-failing` and autopilot leaves the release to a person.

Every review loop (architecture review of the HLD, LLD readiness check, code review) stops after
`reviews.max_rounds` reviews; any blocking finding still open then goes to the person at that
stage's gate instead of another revision round. A re-review sees only the changes since its last
round, and a blocking finding first raised on a re-review that the revision did not introduce is
shown to the person as "late" rather than starting another round.

## Adding a repository

`/maestro-sync` (`$maestro-sync` on Codex) is for one moment: a new repository was added to
the workspace (cloned into `codebase/`, usually registered in `registry.yaml` first). The
engine step (`project_config.py sync`, or `./maestro sync` on its own) adds an empty entry for
each repository on disk that has none; the skill then fills only those entries' stack and
commands and writes the new repositories' docs with `build-knowledge` (each one's
`docs/codebase-maps/<name>.md`, its domain pages, and its place in `docs/architecture.md`). The
engine step reports:

| Report | Meaning |
|---|---|
| `added` | on disk, had no entry; entry added |
| `needs_commands` | no `build` or `test` yet; filled from detect-stack evidence, else by hand |
| `missing_clones` | registered but not cloned; added once it is cloned |
| `unregistered` | cloned but not in `registry.yaml`; added anyway, register it |

It only adds: existing entries are never changed or removed (remove a repository's entry by
hand; preflight warns about one that is no longer in the workspace). The edit keeps the file's
comments and layout, and `--dry-run` reports without writing. A feature already running keeps
the repositories its workspace lock pinned.

## Check it

```bash
python3 .maestro/engine/maestroctl.py preflight
```

| Finding | Level |
|---|---|
| File missing or unreadable | error |
| A repository has no entry under `repos` | error |
| A repository has no `build` or `test` command | error |
| Unknown key inside `repos`, `commands`, `environment`, `design`, `reviews`, `delivery` or `worktree` (a typo) | error |
| `worktree.create` without `worktree.path` (or the reverse), a `path` without `{slug}` and `{repo}` or outside the workspace, an unknown placeholder | error |
| No `lint`, `security` or `e2e` command | warning — that check is skipped |
| A configured repository is not in the workspace | warning |

Issues print to stderr; a JSON summary prints to stdout. The exit code is 1 when there is any
error. Top-level keys other than the ones above are allowed: a workflow can read its own values
with `${config.<path>}`.
