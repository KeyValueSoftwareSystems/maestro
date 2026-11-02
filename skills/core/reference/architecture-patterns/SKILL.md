---
name: architecture-patterns
description: Reference for choosing and reviewing system architecture — when each pattern fits, when it does not, and what it costs. Covers architecture style (modular monolith, services, event-driven, serverless), sync vs async integration, data ownership, outbox and idempotent consumers, sagas, CQRS, caching, BFF/gateway, resilience, horizontal scaling and partitioning, multi-tenancy, and observability. Use when writing or reviewing an HLD.
allowed-tools: Read, Grep, Glob
tags: [reference, architecture]
---

# architecture-patterns

A pattern is a cost you pay for a need you can name. Choose the simplest shape that meets the
requirement's stated load, independence and failure needs, and name the need next to every pattern
you add. Reviewing, flag both sides: a stated need with no mechanism (under-engineering) and a
mechanism with no stated need (over-engineering).

Start from what already exists. Extending the workspace's current style is the default; changing
it is a decision that needs its own justification.

## Architecture style

| Style | Fits when | Costs | Avoid when |
|---|---|---|---|
| Modular monolith | One team, shared release cadence, strong consistency needs | Discipline to keep module boundaries | Parts need independent scaling or deploys now |
| Separate services | Independent scaling, deploy cadence, ownership or failure isolation is a stated need | Network calls, distributed failure, contracts, ops per service | The split only mirrors code folders |
| Event-driven | Producers must not wait on consumers; fan-out; audit/replay | Eventual consistency, ordering, duplicate delivery, harder debugging | The caller needs the result to continue |
| Serverless functions | Spiky or low volume, short work, managed scaling | Cold starts, execution limits, vendor coupling, local testing | Long-running, latency-critical or high steady volume |

A new service needs: an owner, its own data, a reason it cannot be a module, and a deploy and
on-call story.

## Integration

- **Synchronous request/response** — the caller needs the answer now. Set a timeout below the
  caller's own budget, retry only idempotent operations, and define what the caller shows when
  the callee is down.
- **Asynchronous messaging** — the work can finish later, or several consumers react. Every
  consumer is idempotent (dedupe on a message key), poison messages go to a dead-letter queue, and
  the design states the ordering guarantee it relies on (usually per key, not global).
- **Transactional outbox** — a state change and its event must not diverge: write both in one
  local transaction, publish from the outbox. Never "save then publish" across two systems.
- **Saga** — a business process spans services without a distributed transaction: a sequence of
  local steps with a compensating step for each. Prefer orchestration when the flow has more than
  three steps or needs visibility.
- **BFF / API gateway** — a client needs a shaped aggregate of several services, or cross-cutting
  auth/rate limits belong at the edge. Keep business rules out of the gateway.

## Data

- **One owner per piece of state.** Other services read through its API or a published event,
  never its tables.
- **CQRS / read models** — reads and writes differ sharply in shape or volume. Costs a projection
  to keep current and staleness to explain to users.
- **Caching** — a measured read hot path or a slow dependency. State the key, TTL, invalidation
  trigger, what happens on a miss storm, and whether stale data is acceptable. Cache-aside is the
  default; write-through only when reads must see writes immediately.
- **Multi-tenancy** — tenant id on every row and every query path, isolation level chosen
  (shared tables, schema or database per tenant) by the strongest isolation requirement.
- **Migrations** — expand, migrate, contract; old and new code must run against the same schema
  during rollout.

## Resilience

- Timeouts on every remote call; retries with exponential backoff and jitter, capped, only for
  idempotent work.
- Circuit breaker when a failing dependency would exhaust threads or connections.
- Bulkheads (separate pools/queues) so one slow dependency or tenant cannot starve the rest.
- Backpressure: bounded queues and rate limits; shed or defer load instead of collapsing.
- Graceful degradation: state what the feature does when each dependency is unavailable.

## Scaling

- Keep request handlers stateless so instances scale horizontally; session and job state live in
  a store.
- Scale on the signal that tracks the bottleneck: CPU for compute, queue depth or lag for workers,
  connections for databases.
- Databases scale last and hardest: read replicas for read-heavy load, partitioning by a key that
  spreads writes (never by time alone for hot writes), connection pooling before more instances.
- Unbounded work on a hot path (N+1 calls, full scans, unpaginated lists, synchronous fan-out) is
  the usual real bottleneck; fix it before adding capacity.
- Tie every scaling mechanism to a stated target: volume, p95/p99 response time, availability.

## Observability and operations

- Each new flow has a success and failure metric, logs with a correlation id across services, and
  traces through every hop.
- An availability or latency target needs an SLO and an alert on it, not on CPU.
- Rollout: feature flag or staged rollout for risky changes; a backout that does not need a data
  restore; migrations that are safe to run before the code.

## Review heuristics

- "Scalable", "robust", "high-availability" without a mechanism and a number is not a design.
- A queue, cache or service with no requirement that needs it is cost without benefit.
- A synchronous chain of three or more services on a user request multiplies latency and failure.
- Two services writing the same data is a correctness bug waiting for load.
