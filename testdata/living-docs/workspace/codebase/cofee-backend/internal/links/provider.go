package links

type LinkProvider interface{ Create(ctx Context, inv Invoice) (PaymentLink, error) }

var Providers = map[string]LinkProvider{}
