package links

// CreateLinkV0 is the pre-3.2 admin-app path. It does not check for an active link.
func CreateLinkV0(ctx Context, inv Invoice) (PaymentLink, error) { return PaymentLink{}, nil }
