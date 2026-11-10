package links

func PublishDisabled(ctx Context, linkID string) error { return bus.Publish(ctx, "link.disabled", linkID) }
