package links

// ARCH-INV-002: only the backend calls payment providers.
type LinkProvider interface{ Create(ctx Context, inv Invoice) (PaymentLink, error) }

var Providers = map[string]LinkProvider{}
