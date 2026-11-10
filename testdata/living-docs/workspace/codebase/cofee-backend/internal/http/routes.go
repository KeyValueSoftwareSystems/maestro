package http

func Routes(r Router, l *links.Handler, w *webhooks.CashfreeHandler) {
	r.Handle("POST /v1/invoices/{id}/link", l.CreateLink)
	r.Handle("POST /v1/links/{id}/disable", l.Disable)
	r.Handle("GET /v1/links/{id}", l.Get)
	r.Handle("POST /v1/webhooks/cashfree", w.Handle)
}
