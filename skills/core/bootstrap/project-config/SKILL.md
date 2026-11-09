---
name: project-config
description: Write maestro.config.yaml from a detect-stack result. Repo names come from registry.yaml when that file exists. Does not scan the codebase and does not install skills. Called by /maestro-init after detect-stack
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
   `typecheck`, `security`, or `e2e` only when the cited evidence names that script or
   target. `role: infra` when the only tokens are `terraform` and/or `kubernetes`.
3. **Write the report and apply it.**

```bash
python3 .maestro/engine/project_config.py apply --root . --detected .maestro/index/detected-stacks.json
```

The JSON shape is:

```json
{"repos": {"backend": {"stack": "go, db", "commands": {"build": "go build ./...", "test": "go test ./..."}}}}
```

`apply` creates `maestro.config.yaml` when it is missing, copies registry names onto it,
and fills empty `stack` / `commands`. A value already in the file is left unchanged.

## Safety
- The only write is `.maestro/index/detected-stacks.json` and `maestro.config.yaml`.
- Never edit application code. Never touch `.maestro/runs/` state.

## Output contract
Return `created` (whether the config file was new), `updated` (repo names whose empty
fields were filled), and `summary` (one line).
