package webhooks

type CashfreeHandler struct{}

func (h *CashfreeHandler) Handle(w ResponseWriter, r *Request) {
	bus.Publish(ctx, "payment.succeeded", evt)
}
