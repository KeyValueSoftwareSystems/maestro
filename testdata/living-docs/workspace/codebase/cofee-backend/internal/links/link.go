package links

type Service struct{}

// PL-INV-001: reuse the invoice's active link. PL-INV-002: amount in paise (ARCH-INV-001).
// ForInvoice returns the invoice's active link or creates one at Cashfree.
func (s *Service) ForInvoice(ctx Context, inv Invoice) (PaymentLink, error) { return PaymentLink{}, nil }
