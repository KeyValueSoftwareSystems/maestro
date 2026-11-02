# orders-api

Owns orders. `orders/service.py::get_order` backs `GET /orders/<id>`, which returns
`{id, total, paid, shipped}`. The orders-cli client calls it.
