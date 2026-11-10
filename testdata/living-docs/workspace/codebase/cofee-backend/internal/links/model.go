package links

type PaymentLink struct {
	ID          string
	InvoiceID   string
	AmountPaise money.Paise
	Active      bool
}
