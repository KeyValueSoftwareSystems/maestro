---
doc: architecture
id_prefix: ARCH
owner: "CoFee tech lead (Ravi K.)"
repos: [cofee-backend, cofee-payer-app, cofee-admin-app]
verified_at: {}
reviewed: {by: "Ravi K.", date: 2026-11-02}
status: verified
---
> Start here, then open one domain doc. A diagram for people is in _generated/diagrams/architecture.mmd.

# Architecture

## System context and repos
CoFee collects fees for small institutions such as dance schools and tuition centres. Admins set fees and send payment links from the admin app; payers pay through Cashfree from WhatsApp or the payer app.
| Repo or provider | Kind | Purpose | Owns data | Runs on |
| --- | --- | --- | --- | --- |
| cofee-backend | service (Go) | API, jobs and webhooks for every domain | cofee_db | AWS ECS, defined in cofee-backend · deploy/ecs.tf · cofee_backend |
| cofee-admin-app | app (Flutter) | Institution admin app | None. | App stores |
| cofee-payer-app | app (Flutter) | Payer app and web pay page | None. | App stores and web |
| Cashfree | external | Payment links and payment callbacks | Payment records at Cashfree | external |
| WhatsApp Business (Meta) | external | Approved template messages to payers | None. | external |

## Domain map
| Domain | Purpose | Repos | Owner | Technical | Functional |
| --- | --- | --- | --- | --- | --- |
| payment-links | One Cashfree link per invoice, shared by its payers | cofee-backend, cofee-payer-app, cofee-admin-app | payments pod (lead: Meera S.) | [technical](technical/payment-links.md) | [functional](functional/payment-links.md) |

## Cross-repo flows and contracts
| From | To | Operation / event | Protocol | Sync | Auth | Contract |
| --- | --- | --- | --- | --- | --- | --- |
| cofee-admin-app | cofee-backend | Admin operations | REST | sync | admin JWT | cofee-backend · api/openapi.yaml · createInvoiceLink |
| cofee-payer-app | cofee-backend | Payer operations | REST | sync | signed link token | cofee-backend · api/openapi.yaml · getLink |
| cofee-backend | Cashfree | Create payment link | REST | sync | API key | Cashfree link API (external) |
| Cashfree | cofee-backend | Payment callback | webhook | async | HMAC signature | cofee-backend · api/openapi.yaml · cashfreeCallback |
| cofee-backend | WhatsApp Business (Meta) | Send template message | REST | async | API token | Meta Cloud API (external) |

## Platform-wide invariants
| ID | Invariant | Where (repo · path · symbol) | Consistency |
| --- | --- | --- | --- |
| ARCH-INV-001 | Money amounts are int64 paise in code, database and APIs, never float. | cofee-backend · internal/money/paise.go · Paise | checked in review |
| ARCH-INV-002 | Only cofee-backend calls Cashfree and WhatsApp; apps never hold provider keys. | cofee-backend · internal/links/provider.go · LinkProvider | boundary, checked in review |

## Conventions and boundaries
- Payer phone numbers are personal data; logs mask all but the last 4 digits. All customer data stays in AWS ap-south-1.
- Every API error uses the envelope code, message, details from api/openapi.yaml.
- API changes stay backward compatible with every app version above 1% of sessions; checked in API review.
- Risk tiers by code path live in maestro.config.yaml; product docs (feature catalog, PRD index, analytics events) live in docs/product/.

## Glossary and aliases
| Term | Meaning | Code names and aliases | Not to be confused with |
| --- | --- | --- | --- |
| Institution | A customer of CoFee: a school, academy or tuition centre | Institution, institutions table, "centre" (sales) | Group: a batch inside one institution |
| Invoice | The amount one student owes for one period | Invoice, invoices table, "due" (payer app) | Payment link: how an invoice is paid |
