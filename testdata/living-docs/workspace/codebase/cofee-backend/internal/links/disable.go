package links

func (s *Service) Disable(ctx Context, linkID string) error { return PublishDisabled(ctx, linkID) }
