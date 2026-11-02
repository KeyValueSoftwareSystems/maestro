import unittest

from exports.views import export_orders


class ExportTest(unittest.TestCase):
    def test_csv(self):
        self.assertEqual(export_orders([{"id": "A-1", "total": "1"}]), "id,total\nA-1,1")
