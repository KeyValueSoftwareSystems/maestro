package config

type Config struct {
	CashfreeRetryMax int `env:"LINKS_CASHFREE_RETRY_MAX" default:"3"`
	ExpiryDays       int `env:"LINKS_EXPIRY_DAYS" default:"30"`
}
