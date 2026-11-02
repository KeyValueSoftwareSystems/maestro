---
name: kubernetes-patterns
description: Kubernetes, Helm and Kustomize reference for designing and reviewing workload changes — deployments, probes, resources and autoscaling, disruption budgets, config and secrets, networking and ingress, jobs, rollout, and observability. Use when a feature's HLD or LLD changes Kubernetes-managed workloads.
allowed-tools: Read, Grep, Glob, Bash
tags: [stack:kubernetes, patterns, infra]
---

# kubernetes-patterns

## Read the existing layout first

- Find how workloads are packaged: Helm charts (`Chart.yaml`, `values-<env>.yaml`), Kustomize
  bases and overlays, or plain manifests per environment. Extend the chart or base the service
  already uses; per-environment differences go in values or overlays.
- Find the cluster-wide conventions already in place: ingress controller, certificate issuer,
  secret store (External Secrets, Sealed Secrets, CSI), service mesh, autoscaler (HPA, KEDA).

## Workloads

- **Deployment** for stateless services; **StatefulSet** only for workloads that need stable
  identity or storage (prefer a managed data store over running one in the cluster).
- **Probes**: readiness gates traffic (dependencies reachable, warm); liveness only detects a
  stuck process and must not call dependencies; a startup probe for slow starts.
- **Resources**: requests sized from measured usage, limits on memory; CPU limits only when the
  repository already uses them. Requests drive scheduling and HPA percentages.
- **Autoscaling**: HPA on CPU for compute-bound services; KEDA or custom metrics on queue depth or
  lag for workers. State min (availability), max (cost/backing-store limits) and the target, and
  check the database and downstream connection limits at max replicas.
- **Availability**: at least two replicas for user-facing services, a PodDisruptionBudget, and
  topology spread across zones when the cluster spans them.
- **Jobs and CronJobs**: idempotent, `concurrencyPolicy: Forbid` unless overlap is safe,
  `backoffLimit` and `activeDeadlineSeconds` set.
- **Graceful shutdown**: handle SIGTERM, drain in-flight work within
  `terminationGracePeriodSeconds`, and add a short preStop delay when behind a load balancer.

## Config, secrets and networking

- Config in ConfigMaps or chart values; secrets from the existing secret store, never in values
  files or images. Changing config should roll the pods (checksum annotation or a hashed name).
- Services are ClusterIP by default; expose through the existing ingress or gateway with TLS.
- NetworkPolicies follow the repository's default (deny-all plus explicit allows, when used).

## Rollout and safety

- RollingUpdate with `maxUnavailable: 0` for user-facing services; old and new versions must
  run side by side (backward-compatible APIs, expand/contract migrations).
- Database migrations run as a pre-deploy Job or init step that is safe to re-run, never inside
  every pod's start.
- Pin image tags or digests; never `latest`.

## Observability

- Metrics endpoint scraped by the existing stack (ServiceMonitor or annotations), structured logs
  to stdout, and alerts on the SLO the requirement states.

## Verifying

- `helm lint` / `helm template` or `kustomize build` for every environment, then schema validation
  (kubeconform) and the repository's policy checks when present.
- The LLD for the chart or manifests names each object added or changed and its per-environment
  values (replicas, resources, autoscaling bounds).
