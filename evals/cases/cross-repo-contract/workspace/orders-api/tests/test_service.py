import unittest

from orders.service import get_order


class ServiceTest(unittest.TestCase):
    def test_known_order(self):
        self.assertEqual(get_order("A-1")["total"], "40.00")

    def test_unknown_order(self):
        self.assertIsNone(get_order("missing"))
