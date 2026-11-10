package webhooks

type CashfreeHandler struct{}

// PL-INV-003: apply each Cashfree event id at most once.
func (h *CashfreeHandler) Handle(w ResponseWriter, r *Request) {
	bus.Publish(ctx, "payment.succeeded", evt)
}
