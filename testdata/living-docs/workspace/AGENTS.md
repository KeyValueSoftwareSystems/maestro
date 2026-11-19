# cofee-workspace
Umbrella for CoFee. Product code lives in repos/; docs/ is the system of record.

## Map
- repos/cofee-backend: Go API, jobs and webhooks. Commands in its CLAUDE.md.
- repos/cofee-admin-app, repos/cofee-payer-app: Flutter apps.
- docs/architecture.md: repos, domain map, cross-repo flows, platform rules. Read first.
- docs/<domain>.md: one per domain, rules first, then invariants and gotchas, then the generated
  connections and inventory. Read only the part you need (living_docs.py show <domain> --part ...).

## Rules that apply everywhere
- Money is int64 paise, never float (ARCH-INV-001).
- Only cofee-backend talks to Cashfree and WhatsApp (ARCH-INV-002).
- Never hand-edit a generated file or block; run the checker with --write.
- Cite rules by ID (PL-BR-001, PL-INV-001, PL-CS-001) in designs, PRs and code comments.
