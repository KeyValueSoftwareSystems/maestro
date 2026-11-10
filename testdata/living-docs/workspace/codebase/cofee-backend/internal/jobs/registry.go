package jobs

func init() {
	Register("link-expiry-sweep", "30 1 * * *", links.ExpirySweep{}.Run)
}
