# Recommended: run Maestro from an umbrella workspace

Maestro runs fine inside a single repo. But an SDLC pipeline produces its best output when the
lead agent can *see the whole feature at once* — frontend, backend, every microservice, the docs,
and the cross-repo tests — instead of one repo in isolation. The way to give it that surface is an
**umbrella workspace**: one parent git repo per project into which you install the Maestro pack and
under which you check out the service repos you're actually changing.

Set this up once per project, then run every feature from the umbrella root. It's a per-project
setup you do manually — the pack doesn't scaffold it for you (yet).

```
my-project/                 ← umbrella repo (git init once; this is where you run /maestro)
├── maestro                 ← the ./maestro wrapper           ┐  installed by install.sh
├── engine/  workflows/  ui/  docs/                           ┘  (regenerated on upgrade)
├── .claude/  .cursor/      ← skills / commands / agents      ┘
├── .maestro/<slug>/        ← per-feature requirement + artifacts + run ledger
├── codebase/               ← service repos, each cloned here, each GITIGNORED
│   ├── frontend/           ← independent repo: own branches, PRs, CI
│   │   └── CLAUDE.md        ← that repo's conventions (or .cursor/rules/*.mdc)
│   ├── backend/
│   │   └── CLAUDE.md
│   └── payments-service/
├── docs/                   ← centralised, cross-repo (technical / functional / business)
├── test/                   ← cross-repo integration + UI-automation suites
├── compose.yaml            ← (or Tiltfile) one command to bring the stack up
├── SETUP.md                ← human-owned host prerequisites + secrets
└── workspace.yaml          ← manifest listing the child repos (your convention)
```

## The setup, in order

- **One parent repo, N child clones — not a monorepo.** Keep every service repo independent
  (its own branches, PRs, CI). Do **not** merge them together. Instead clone each one, **gitignored**,
  under `codebase/` in the umbrella, so a single agent sees the whole stack at once. A small
  `workspace.yaml` manifest listing the repos keeps the checkout reproducible for teammates.

- **Give every child repo its own agent guidance file.** Each service repo under `codebase/` should
  carry a `CLAUDE.md` (Claude Code) and/or a `.cursor/rules/*.mdc` / `.cursorrules` (Cursor) at its
  root, describing *that repo's* conventions — stack, build/test/run commands, directory layout,
  house style, gotchas. When the agent edits `codebase/backend/`, its `CLAUDE.md` is what tells it
  how that service is built and tested. Keep these committed **in each service repo** (they're
  repo-specific and useful outside Maestro too); the umbrella's own `CLAUDE.md`, if any, covers only
  cross-repo/workspace concerns. Without them the agent guesses per-repo conventions from the code —
  the files make its output match each team's norms.

- **Install Maestro into the umbrella root.** Run the installer (or `./maestro install`) from the
  umbrella, not inside a service repo. That drops `engine/`, `workflows/`, `ui/`, the `maestro`
  wrapper and the skills into the parent, and every run's `.maestro/<slug>/` — requirement input
  and all generated artifacts — lives there. The umbrella is the agent's working surface; the child
  repos under `codebase/` are what it edits.

- **Seed domain knowledge.** After installing, run `/build-knowledge` once from the umbrella
  root to populate `.maestro/memory/knowledge/` from the cloned repos + their `CLAUDE.md` and
  the centralised `docs/`. Feature runs read this (frozen at init) to ground their designs and
  reviews; it's re-runnable and merges. See [memory.md](memory.md).

- **Git prerequisite still applies per child repo.** The per-stack implement steps run in isolated
  `git worktree`s, so each service repo you touch must be an initialised git repo with at least one
  commit (`git init && git add -A && git commit`). The umbrella itself should also be a git repo so
  the run ledger (`.maestro/<slug>/`) is tracked and a run resumes on any machine.

- **Docs + tests centralised in the umbrella.** Keep the per-feature docs tree
  (`docs/technical`, `docs/functional`, `docs/business`) and the cross-repo integration +
  UI-automation suites (`test/integration`, `test/ui-automation`) in the umbrella, so one suite
  spans every repo.

- **Connect source-of-truth MCPs.** The design flow assumes a PRD and designs already exist —
  connect Jira / Confluence / Figma over MCP so the agent reads tickets, specs, and designs
  directly instead of you pasting them in.

## Local testing — one command to bring the stack up

The QA and verify steps are far more useful when the agent can actually *run* the stack and hit it,
not just reason about the diff. Wire the whole workspace up and down behind a **single command** so
the agent (and every teammate) starts it the same way. Two common choices:

**Docker Compose** — good when every service already ships a `Dockerfile`. Put a `compose.yaml` at
the umbrella root that builds each child repo under `codebase/` and wires up datastores:

```yaml
# my-project/compose.yaml
services:
  frontend:
    build: ./codebase/frontend
    ports: ["3000:3000"]
    depends_on: [backend]
  backend:
    build: ./codebase/backend
    ports: ["8080:8080"]
    environment: [DATABASE_URL=postgres://app:app@db:5432/app]
    depends_on: [db]
  db:
    image: postgres:16
    environment: [POSTGRES_USER=app, POSTGRES_PASSWORD=app, POSTGRES_DB=app]
```

```bash
docker compose up -d --build     # bring the whole stack up
docker compose down -v           # tear it down
```

**Tilt** — better for an active edit-loop: live-reloads each service on change and gives one
dashboard across repos. A root `Tiltfile` references the same per-repo Dockerfiles / k8s manifests:

```python
# my-project/Tiltfile
docker_build('frontend', './codebase/frontend')
docker_build('backend',  './codebase/backend')
k8s_yaml('deploy/dev.yaml')
```

```bash
tilt up      # start + watch the stack
tilt down    # stop it
```

Whichever you pick, expose it as one wrapper command (e.g. `stack up` / `stack down`) so it's the
same in the docs, in CI, and in what the agent runs. **Host prerequisites and secrets stay
human-owned** in a `SETUP.md` (API keys, cloud creds, `.env` files) — the workflow reads them but
never creates or commits them.

## Running a feature

From the umbrella root, exactly as in a single repo:

```
/maestro my-feature                          # full pipeline across the cloned stack
/maestro my-feature workflows/design.yaml    # just one phase
```

The lead agent scaffolds `.maestro/my-feature/requirement/`, reads the whole workspace, and writes
every artifact under `.maestro/my-feature/` — while editing the actual service repos under
`codebase/` in their own worktrees.

> Release ordering: **approve release → archival (harvest lessons into memory + publish
> curated docs) → merge the feature branch to master.** Archival is the last automated phase;
> Maestro does not perform the merge itself.

> The umbrella is a per-project convention, not something this pack ships. Set it up manually; the
> pack installs into it and every feature lives under `.maestro/<slug>/` inside it.
