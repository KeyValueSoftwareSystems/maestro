"""Order lookups served to clients as JSON-ready dicts."""

ORDERS = {
    "A-1": {"id": "A-1", "total": "40.00", "paid": True, "shipped": False},
    "A-2": {"id": "A-2", "total": "15.50", "paid": False, "shipped": False},
}


def get_order(order_id):
    """GET /orders/<id> — the order, or None when it does not exist."""
    order = ORDERS.get(order_id)
    return dict(order) if order else None
