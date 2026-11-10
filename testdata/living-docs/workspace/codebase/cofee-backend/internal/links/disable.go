package links

// PL-INV-004: disabling stops new reminders for the invoice.
func (s *Service) Disable(ctx Context, linkID string) error { return PublishDisabled(ctx, linkID) }
