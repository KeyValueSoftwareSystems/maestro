---
name: terraform-patterns
description: Terraform reference for designing and reviewing infrastructure changes — module structure, state and environments, safe plans, capacity and scaling settings, networking, secrets, and change safety. Use when a feature's HLD or LLD changes Terraform-managed infrastructure.
allowed-tools: Read, Grep, Glob, Bash
tags: [stack:terraform, patterns, infra]
---

# terraform-patterns

## Read the existing layout first

- Find the root modules (directories with a backend/provider block) and which environment each
  one deploys (`envs/<env>`, workspaces, or `*.tfvars` per environment). A change usually lands in
  a shared module plus a per-environment value.
- Find the modules the feature's services already use (compute, database, queue, cache, DNS) and
  extend those instead of adding a parallel resource.
- Note the state backend and locking (S3 + DynamoDB, GCS, Terraform Cloud). Never design a change
  that needs manual state edits.

## Designing a change

- **New resources go in a module** with typed variables, defaults that are safe for production,
  and outputs the application needs (endpoints, ARNs/ids, secret names) — never hard-coded ids.
- **Capacity is a variable per environment**: instance counts, autoscaling min/max and target,
  database instance class and storage, queue retention, cache node size. State the production
  value in the HLD and why it meets the PRD's targets.
- **Networking**: new services join the existing VPC/subnets and security groups; open only the
  ports and sources the interface needs; private by default, public only behind the existing
  load balancer or gateway.
- **Secrets** come from the existing secret manager (Secrets Manager, Vault, SSM, Secret
  Manager) by reference; never in variables, tfvars or state outputs marked non-sensitive.
- **Data stores**: enable backups and point-in-time recovery, deletion protection, encryption at
  rest; size connections for the instance count times pool size.
- **IAM**: least privilege per service role; one role per workload, no wildcard actions on
  production resources.
- **Tags/labels**: follow the repository's tagging convention (owner, environment, cost centre).

## Change safety

- Read the plan for every environment: any `destroy` or `forces replacement` on a stateful
  resource (database, volume, bucket, queue) is a design problem, not a detail — use
  `create_before_destroy`, `moved` blocks, or a migration step.
- Renames use `moved {}` blocks; never delete-and-recreate to rename.
- Roll out to non-production first; production changes that cause downtime need a window or a
  blue/green path stated in the HLD.
- Pin provider and module versions; upgrade them in their own change.

## Verifying

- `terraform fmt -check`, `terraform validate`, and a plan per environment in CI; a policy or lint
  step (tflint, checkov, tfsec) when the repository has one.
- The LLD for an infrastructure repository names each resource added or changed, its per-environment
  values, and the plan output it expects (adds/changes, no destroys of stateful resources).
