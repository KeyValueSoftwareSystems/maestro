Future<Link> createInvoiceLink(String id) => http.post('/v1/invoices/$id/link');
Future<void> disableLink(String id) => http.post('/v1/links/$id/disable');
