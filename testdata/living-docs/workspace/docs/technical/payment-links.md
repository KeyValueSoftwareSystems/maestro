---
doc: technical
domain: payment-links
id_prefix: PL
owner: "payments pod (lead: Meera S.)"
repos: [cofee-backend, cofee-payer-app, cofee-admin-app]
code_roots: [cofee-backend/internal/links, cofee-backend/internal/webhooks, cofee-backend/internal/config/links.go, cofee-payer-app/lib/pay]
verified_at: {}
reviewed: {by: "Meera S.", date: 2026-11-02}
status: verified
---
> payment-links technical. Rules PL-BR-* are in functional/payment-links.md. Endpoints, events, jobs, data and config are generated in _generated/payment-links.inventory.md.

# payment-links: Technical

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

## Cross-repo connections
<!-- generated:connections begin; from code by living_docs.py; do not edit -->
| From (repo · path · function) | To | Operation | Handler |
| --- | --- | --- | --- |
| cofee-admin-app · lib/api/links_api.dart · createInvoiceLink | cofee-backend | POST /v1/invoices/{id}/link | cofee-backend · internal/links/handler.go · Handler.CreateLink |
| cofee-admin-app · lib/api/links_api.dart · disableLink | cofee-backend | POST /v1/links/{id}/disable | cofee-backend · internal/links/handler.go · Handler.Disable |
| cofee-payer-app · lib/api/links_api.dart · getLink | cofee-backend | GET /v1/links/{id} | cofee-backend · internal/links/handler.go · Handler.Get |
<!-- generated:connections end -->

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

## Known gaps and tech debt
- PL-INV-004 has no automated test. Unknown. (ask: payments pod lead, since 2026-11-02)
- Whether revenue reports read payment_links nightly or in real time: Unknown. (ask: data lead, since 2026-11-02)
- CreateLinkV0 is still called by cofee-admin-app below 3.2.0; removal waits until those versions fall under 1% of sessions.
