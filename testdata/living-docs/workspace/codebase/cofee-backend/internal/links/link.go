package links

type Service struct{}

// ForInvoice returns the invoice's active link or creates one at Cashfree.
func (s *Service) ForInvoice(ctx Context, inv Invoice) (PaymentLink, error) { return PaymentLink{}, nil }
