# Rubric — infra-queue

Score each criterion 1–5.

- **architecture_judgement** — an async job on a queue with a worker is chosen for the stated
  reason (request time-outs, the 5-minute target); idempotent retries; a dead-letter path; status
  the client can poll. No over-engineering (no new service mesh, no new database).
- **targets_met** — the HLD shows how 100,000 rows in 5 minutes and 50 requests per minute are met
  (worker count or autoscaling bound, queue sizing) and how the 7-day deletion is enforced (bucket
  lifecycle rule).
- **infrastructure_delivered** — the platform repository's LLD and change add the queue, its
  dead-letter queue, the worker's deployment and the lifecycle rule, each with production values;
  the application consumes them under the same names.
- **questions** — infrastructure questions were asked (scaling, retention, retries) and only those
  the requirement and Terraform did not already answer.
- **evidence** — verification, the acceptance-criteria trace, drift and assumptions are reported
  honestly.
