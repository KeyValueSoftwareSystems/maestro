---
name: project-config
description: Write maestro.config.yaml from a detect-stack result. Repo names come from registry.yaml when that file exists; a workspace sandbox script's documented commands become the worktree settings, an infra script's the environment settings. Does not scan the codebase and does not install skills. Called by /maestro-init after detect-stack
allowed-tools: Bash
tags: [maestro, bootstrap]
---

# project-config — write maestro.config.yaml from a detect-stack result

Turn the per-repo stacks **detect-stack already returned** into `maestro.config.yaml`.
This skill does not scan the tree, does not install skills, and does not build the
knowledge base.

## When to use
`/maestro-init` runs this after detect-stack. Do not run it from detect-stack. If you have
no detect-stack `repos` result, stop and run detect-stack first — do not detect stacks here.

## Inputs
- detect-stack `repos`: `{name, stacks, evidence}` per repository
- `registry.yaml` at the workspace root, when Maestro is installed in the template

## Steps
1. **Repo names.** When `registry.yaml` exists, those `name` fields are the config keys.
   Otherwise use the names detect-stack returned.
2. **Stack and commands from that result only.** For each name, `stack` is that repo's
   tokens, comma-separated, in detect-stack vocabulary order. Commands come from the
   evidence files detect-stack already cited — do not open the repo again:

   | Evidence already cited | build | test |
   | --- | --- | --- |
   | `Makefile` / `makefile` with those targets | `make build` | `make test` |
   | `package.json` scripts | `npm run build` (`pnpm` / `yarn` if that lockfile was cited) | `npm test` |
   | `go.mod` | `go build ./...` | `go test ./...` |
   | `pom.xml` | `mvn -q -DskipTests package` | `mvn -q test` |
   | `build.gradle` or `build.gradle.kts` | `./gradlew assemble` (or `gradle` when no wrapper was cited) | `./gradlew test` |
   | `pyproject.toml`, `requirements.txt`, `setup.py`, `Pipfile` | `python -m compileall -q .` | `pytest`, or `python manage.py test` when `manage.py` was cited |
   | `Cargo.toml` | `cargo build` | `cargo test` |
   | `pubspec.yaml` | `flutter analyze` | `flutter test` |
   | `*.tf` and no application stack | `terraform fmt -check -recursive && terraform init -backend=false` | `terraform validate` |

   A Makefile target wins over the language default for that command. Add `lint`,
   `typecheck` or `security` only when the cited evidence names that script or target. Never
   put `e2e` under `commands`: copy each repo's detect-stack `e2e` proposal unchanged into the
   report as that repo's `e2e`; the engine runs its list command or checks its evidence and
   writes `commands.e2e` only when it confirms the suite. `role: infra` when the only tokens are
   `terraform` and/or `kubernetes`.
3. **Worktrees, only when the workspace has a sandbox command.** When the workspace root has a
   script that creates a per-feature workspace of worktrees (e.g. `scripts/sandbox`), read its
   usage (`--help`, or the script's header comment) and add a `worktree` section to the report:
   `create` (the command that makes one feature's worktrees for every repository, non-interactive,
   with `{slug}` for the feature name), `path` (where it leaves each repository, with `{slug}` and
   `{repo}`), `branch` (the branch it checks out, when the usage states one) and `remove` (the
   command that deletes that feature's worktrees). Copy what the script documents; never guess a
   flag it does not show. No such script, or its usage is unclear: leave `worktree` out — Maestro
   then creates its own worktrees.
4. **Environment, only when the workspace has a script that runs the stack.** When the workspace
   root has a script that starts and stops the whole stack (e.g. `scripts/infra`), read its usage
   the same way and add an `environment` section: `start` (starts the stack in the background,
   non-interactive), `stop` (stops it) and `ready` (a command that exits 0 only once the stack is
   healthy, when the usage shows one). When the script takes a per-feature target and the
   `worktree` section uses the same script family, pass the feature as `"$MAESTRO_SLUG"` (the
   engine sets it) so the stack runs from that feature's worktrees. Never guess a flag the usage
   does not show; no such script, or no clear start and stop: leave `environment` out.
5. **Write the report and apply it.**

```bash
python3 .maestro/engine/project_config.py apply --root . --detected .maestro/index/detected-stacks.json
```

The JSON shape is:

```json
{"repos": {"backend": {"stack": "go, db", "commands": {"build": "go build ./...", "test": "go test ./..."},
                      "e2e": {"command": null, "reason": "no E2E framework or suite found"}},
           "web": {"stack": "react", "commands": {"build": "npm run build", "test": "npm test"},
                   "e2e": {"command": "npm run test:e2e", "list": "npx playwright test --list",
                           "framework": "playwright", "evidence": ["package.json"]}}},
 "worktree": {"create": "./scripts/sandbox create {slug} -y", "path": "sandbox/{slug}/codebase/{repo}",
              "branch": "sandbox/{slug}", "remove": "./scripts/sandbox rm {slug} -y"},
 "environment": {"start": "./scripts/infra up \"$MAESTRO_SLUG\"",
                 "stop": "./scripts/infra down \"$MAESTRO_SLUG\""}}
```

`apply` creates `maestro.config.yaml` when it is missing, copies registry names onto it,
and fills empty `stack` / `commands`. A value already in the file is left unchanged; `worktree`
and `environment` are each added only when the file has none. For each `e2e` proposal on a repo
without an `e2e` command it records the engine's verdict as that repo's `e2e`
(`status: verified` plus `commands.e2e`, or `status: none` with the reason); its output's `e2e`
map says which. Show the person any `worktree`
section it added — it decides where every feature's code is written — and any `environment`
section — QA starts and stops the stack with it.

## Safety
- The only write is `.maestro/index/detected-stacks.json` and `maestro.config.yaml`. Read a
  sandbox or infra script's usage; never run its create, remove, start or stop commands here.
- Never edit application code. Never touch `.maestro/runs/` state.

## Output contract
Return `created` (whether the config file was new), `updated` (repo names whose empty
fields were filled), and `summary` (one line, naming the worktree and environment commands when
added and the E2E suites confirmed).
