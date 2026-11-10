---
doc: functional
domain: payment-links
id_prefix: PL
owner: "payments pod (lead: Meera S.)"
repos: [cofee-backend, cofee-payer-app, cofee-admin-app]
verified_at: {}
reviewed: {by: "Meera S.", date: 2026-11-02}
status: verified
---
> payment-links functional. How it is built is in technical/payment-links.md. Shared terms (Invoice, Institution) are in architecture.md.

# payment-links: Functional

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

## Open questions and owned unknowns
- Whether a disabled payment link can be re-enabled or must be replaced: Unknown. (ask: product lead, since 2026-11-02)
