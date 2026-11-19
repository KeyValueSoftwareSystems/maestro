---
doc: domain
domain: payment-links
id_prefix: PL
owner: "payments pod (lead: Meera S.)"
repos: [cofee-backend, cofee-payer-app, cofee-admin-app]
code_roots: [cofee-backend/internal/links, cofee-backend/internal/webhooks, cofee-backend/internal/config/links.go, cofee-payer-app/lib/pay]
verified_at: {}
reviewed: {by: "Meera S.", date: 2026-11-02}
status: verified
---
> payment-links. Shared terms are in architecture.md.

# payment-links

## Purpose and actors
Payment links let a payer pay one invoice through Cashfree, from a WhatsApp message or the payer app. Institution admins and CoFee support send, resend and disable links from Admin app · Invoice detail; payers pay from the web pay page or payer app · Pay screen. Out of scope: invoice amounts (fee-collection), when reminders go out (reminders), refunds (not supported).

## Glossary and aliases
| Term | Meaning | Code names and aliases | Not to be confused with |
| --- | --- | --- | --- |
| Payment link | A Cashfree URL that pays one invoice | PaymentLink, payment_links table, "pay link" (support), link_id (logs) | Invoice: the amount owed |
| Payer | A phone number that receives payment links for a student | payer, member_payers table, "parent" (admin app) | Student: the person the fee is for |
| Disable | An admin stops a payment link from taking new payments | Service.Disable, "deactivate" (admin app) | Expire: automatic, after LINKS_EXPIRY_DAYS |

## Business rules
| ID | Rule | Edge | Why / source |
| --- | --- | --- | --- |
| PL-BR-001 | One invoice has one active payment link, and every payer of that invoice gets the same link. | If two payers both pay the same link, Cashfree accepts both; support refunds the second by hand. | Stops two parents paying the same fee; fee-groups PRD AC-06 |
| PL-BR-002 | Disabling a payment link stops reminders for that invoice. | A payment that arrives after the disable is accepted and the invoice is flagged for the admin, never refused. | Admin complaints in 2025 support tickets |
| PL-BR-003 | A payment is credited once, however many times Cashfree reports it. | None. | Cashfree retries callbacks; incident INC-2025-07 |
| PL-BR-004 | An unpaid payment link expires after 30 days; resending creates a new link for the same invoice. | None. | Unknown. (ask: product lead, since 2026-11-02) |

## States and flows
| From | To | Trigger | Actor | Guard |
| --- | --- | --- | --- | --- |
| Payment link: none | active | Admin sends a link, or a scheduled fee run creates one | Institution admin, fee schedule | PL-BR-001 |
| Payment link: active | paid | Cashfree confirms the payment | Cashfree | PL-BR-003 |
| Payment link: active | disabled | Admin disables the link | Institution admin | PL-BR-002 |
| Payment link: active | expired | 30 days pass unpaid | Nightly expiry | PL-BR-004 |
- Pay from WhatsApp: payer taps the link, the pay page shows student, month and amount, payer pays on Cashfree, and the pay page and admin app both show paid; a disabled link shows "link expired" (PL-BR-002).

## Invariants and consistency
| ID | Invariant | Enforces | Where (repo · path · symbol) | Consistency | Tested by |
| --- | --- | --- | --- | --- | --- |
| PL-INV-001 | An invoice has at most one active payment link, shared by every payer of that invoice. | PL-BR-001 | cofee-backend · internal/links/link.go · Service.ForInvoice | transactional: partial unique index one_active_link on payment_links | cofee-backend · internal/links/link_test.go · TestForInvoiceReusesActiveLink |
| PL-INV-002 | A payment link's amount equals its invoice's amount in paise, never a float. | ARCH-INV-001 | cofee-backend · internal/links/link.go · Service.ForInvoice | transactional | cofee-backend · internal/links/link_test.go · TestLinkAmountInPaise |
| PL-INV-003 | A Cashfree callback is applied at most once per Cashfree event id. | PL-BR-003 | cofee-backend · internal/webhooks/cashfree.go · CashfreeHandler.Handle | transactional: primary key on webhook_events.provider_event_id | cofee-backend · internal/webhooks/cashfree_test.go · TestDuplicateCallbackIgnored |
| PL-INV-004 | Disabling a payment link stops new reminders for that invoice within one reminder run. | PL-BR-002 | cofee-backend · internal/links/disable.go · Service.Disable | eventual: next reminder run, at most 15 min | Unknown. (ask: payments pod lead, since 2026-11-02) |

## Change scenarios
| ID | When changing | Also affects | Verify with | Source |
| --- | --- | --- | --- | --- |
| PL-CS-001 | Disabling a payment link: cofee-backend · internal/links/disable.go · Service.Disable | Reminders stop for that invoice (PL-INV-004); a late Cashfree payment is still accepted (PL-BR-002 edge); payer sees cofee-payer-app · lib/pay/link_expired_screen.dart · LinkExpiredScreen | cofee-backend · internal/links/disable_test.go · TestDisablePublishesEvent; cofee-payer-app · test/pay/link_expired_screen_test.dart · LinkExpiredScreen | Incident INC-2025-07 |
| PL-CS-002 | Cashfree retry settings: cofee-backend · internal/config/links.go · Config.CashfreeRetryMax | A changed idempotency key creates two Cashfree links for one invoice (PL-INV-001); payments stuck as pending | cofee-backend · internal/links/link_test.go · TestRetryKeepsIdempotencyKey | Review comment on PR #418 |
| PL-CS-003 | Payment-link amount handling: cofee-backend · internal/links/link.go · Service.ForInvoice | Revenue report totals; the amount in the WhatsApp reminder template (reminders domain); ARCH-INV-001 | cofee-backend · internal/links/link_test.go · TestLinkAmountInPaise | Domain owner, 2026-11-02 |

## Proposed rules and scenarios
| Kind | Proposal | Where (repo · path · symbol) | Evidence |
| --- | --- | --- | --- |
| invariant | A payment link's expiry date never moves earlier once sent. | cofee-backend · internal/links/sweep.go · ExpirySweep.Run | The sweep only expires links past their date; no code shortens it. |

## Failure, concurrency and idempotency
- Two admins send a link for one invoice at once: Service.ForInvoice hits the one_active_link index on the second insert and returns the first link; see PL-INV-001.
- Cashfree retries a payment callback: CashfreeHandler.Handle drops repeats by Cashfree event id; see PL-INV-003.
- A payment arrives after its link was disabled: CashfreeHandler.Handle still records it and flags the invoice for the admin, never drops money; see PL-BR-002.
- Cashfree link API times out: Service.ForInvoice retries up to LINKS_CASHFREE_RETRY_MAX times with the same idempotency key, so a retry never creates a second Cashfree link; see PL-CS-002.

## Gotchas
- Do not copy CreateLinkV0 (cofee-backend · internal/links/legacy.go · CreateLinkV0): it creates a Cashfree link without checking for an active one, which breaks PL-INV-001. Use Service.ForInvoice.
- To add a payment provider, implement LinkProvider (cofee-backend · internal/links/provider.go · LinkProvider) and register it in Providers.
- Alert cashfree-webhook-errors (5xx above 2% for 10 min) means callbacks are failing and parents who paid may still see pending; start at dashboard Payments/Webhooks; related PL-INV-003.
- Alert link-expiry-sweep-failed means expired links stay active and parents can still pay old invoices; start at logs job=link-expiry-sweep; related PL-BR-004.

## Open questions and known gaps
- Whether a disabled payment link can be re-enabled or must be replaced: Unknown. (ask: product lead, since 2026-11-02)
- PL-INV-004 has no automated test. Unknown. (ask: payments pod lead, since 2026-11-02)
- Whether revenue reports read payment_links nightly or in real time: Unknown. (ask: data lead, since 2026-11-02)
- CreateLinkV0 is still called by cofee-admin-app below 3.2.0; removal waits until those versions fall under 1% of sessions.

## Cross-repo connections
<!-- generated:connections begin; from code by living_docs.py; do not edit -->
| From (repo · path · function) | To | Operation | Handler |
| --- | --- | --- | --- |
| cofee-admin-app · lib/api/links_api.dart · createInvoiceLink | cofee-backend | POST /v1/invoices/{id}/link | cofee-backend · internal/links/handler.go · Handler.CreateLink |
| cofee-admin-app · lib/api/links_api.dart · disableLink | cofee-backend | POST /v1/links/{id}/disable | cofee-backend · internal/links/handler.go · Handler.Disable |
| cofee-payer-app · lib/api/links_api.dart · getLink | cofee-backend | GET /v1/links/{id} | cofee-backend · internal/links/handler.go · Handler.Get |
<!-- generated:connections end -->

## Inventory
<!-- generated:inventory begin; from code by living_docs.py; do not edit -->
### APIs
| Operation | Owner repo | Handler | Called by | Contract |
| --- | --- | --- | --- | --- |
| GET /v1/links/{id} | cofee-backend | cofee-backend · internal/links/handler.go · Handler.Get | cofee-payer-app · lib/api/links_api.dart · getLink | cofee-backend · api/openapi.yaml · getLink |
| POST /v1/invoices/{id}/link | cofee-backend | cofee-backend · internal/links/handler.go · Handler.CreateLink | cofee-admin-app · lib/api/links_api.dart · createInvoiceLink | cofee-backend · api/openapi.yaml · createInvoiceLink |
| POST /v1/links/{id}/disable | cofee-backend | cofee-backend · internal/links/handler.go · Handler.Disable | cofee-admin-app · lib/api/links_api.dart · disableLink | cofee-backend · api/openapi.yaml · disableLink |
| POST /v1/webhooks/cashfree | cofee-backend | cofee-backend · internal/webhooks/cashfree.go · CashfreeHandler.Handle | None. | cofee-backend · api/openapi.yaml · cashfreeCallback |

### Events
| Event | Producers | Consumers |
| --- | --- | --- |
| link.disabled | cofee-backend · internal/links/events.go · PublishDisabled | None. |
| payment.succeeded | cofee-backend · internal/webhooks/cashfree.go · CashfreeHandler.Handle | None. |

### Jobs
| Job | Trigger | Owner repo | Runs |
| --- | --- | --- | --- |
| link-expiry-sweep | cron 30 1 * * * | cofee-backend | cofee-backend · internal/links/sweep.go · ExpirySweep.Run |

### Data
| Table | Owner repo | Schema |
| --- | --- | --- |
| payment_links | cofee-backend | cofee-backend · migrations/0007_payment_links.sql · payment_links |
| webhook_events | cofee-backend | cofee-backend · migrations/0007_payment_links.sql · webhook_events |

### Config
| Key | Default | Owner repo | Read in |
| --- | --- | --- | --- |
| LINKS_CASHFREE_RETRY_MAX | 3 | cofee-backend | cofee-backend · internal/config/links.go · Config.CashfreeRetryMax |
| LINKS_EXPIRY_DAYS | 30 | cofee-backend | cofee-backend · internal/config/links.go · Config.ExpiryDays |
<!-- generated:inventory end -->
