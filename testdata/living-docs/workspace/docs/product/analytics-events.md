# Analytics events
> Every Mixpanel event CoFee sends. Tara reuses rows here before adding new ones.

| Event | Fires when | Properties | Surface | Domain | Owner |
| --- | --- | --- | --- | --- | --- |
| fee_link_sent | A payment link is sent to a payer | invoice_id, channel | cofee-backend | payment-links | payments pod |
| fee_paid | Cashfree confirms a payment | invoice_id, amount_paise, days_since_sent | cofee-backend | payment-links | payments pod |
| link_disabled | An admin disables a payment link | invoice_id | Admin app · Invoice detail | payment-links | payments pod |
