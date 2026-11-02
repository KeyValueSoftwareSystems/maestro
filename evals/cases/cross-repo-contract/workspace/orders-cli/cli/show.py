"""Print an order the way support staff read it."""


def render(order):
    """One line for an order dict returned by GET /orders/<id>."""
    return f"{order['id']}: {order['total']}"
