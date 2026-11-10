CREATE TABLE payment_links (id text primary key, invoice_id text not null, amount_paise bigint not null, active boolean not null);
CREATE UNIQUE INDEX one_active_link ON payment_links(invoice_id) WHERE active;
CREATE TABLE webhook_events (provider_event_id text primary key, link_id text not null);
