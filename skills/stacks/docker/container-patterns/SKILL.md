---
name: container-patterns
description: Dockerfile and Docker Compose reference for designing and reviewing container changes — images, runtime config and secrets, ports, health checks, resources, local and QA stacks. Use when a feature adds or changes a containerized service or the Compose stack.
allowed-tools: Read, Grep, Glob, Bash
tags: [stack:docker, patterns, infra]
---

# container-patterns

## Read the existing setup first

- Find each service's Dockerfile and the Compose files (`docker-compose*.yml`, `compose.yaml`,
  per-environment overrides). A new service follows the nearest existing one: same base image
  family, build stages, user, healthcheck style and network.

## Images

- Multi-stage builds: build tools in the builder stage, a minimal runtime stage.
- Pin base images to a version (and digest where the repository does); never `latest`.
- Run as a non-root user; copy only what the runtime needs; a `.dockerignore` keeps secrets and
  build output out of the context.
- One process per container; background workers are their own service sharing the image.

## Runtime

- Configuration through environment variables with documented defaults; secrets from the
  existing mechanism (Compose secrets, an env file outside git, the platform's secret store),
  never baked into the image or committed.
- Expose only the ports the interface needs; services talk over the Compose network by service
  name, not host ports.
- A healthcheck that reflects readiness; `depends_on` with `condition: service_healthy` so the
  stack starts in order.
- Set memory limits for services that can grow (workers, caches) so one cannot starve the host.
- Named volumes for data that must survive restarts; none for stateless services.

## Local and QA stacks

- The Compose stack should build from a given checkout path so QA can run it against the exact
  code under test (for example `build: ${MAESTRO_WORKTREE_BACKEND:-./backend}`).
- Seed data and migrations run as a one-shot service or script that is safe to re-run.

## Verifying

- `docker build` for each changed image, `docker compose config` to validate the Compose files,
  and the repository's image scan or lint (hadolint, trivy) when present.
- The LLD names each service, image, port, variable and volume added or changed.
