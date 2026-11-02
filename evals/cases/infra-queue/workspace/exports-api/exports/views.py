"""Report exports. Today the export is built inside the request."""


def export_orders(rows):
    """POST /exports — returns the CSV text for the given rows."""
    lines = ["id,total"] + [f"{r['id']},{r['total']}" for r in rows]
    return "\n".join(lines)
