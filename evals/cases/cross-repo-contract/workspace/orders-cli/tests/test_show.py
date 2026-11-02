import unittest

from cli.show import render


class RenderTest(unittest.TestCase):
    def test_render(self):
        self.assertEqual(render({"id": "A-1", "total": "40.00"}), "A-1: 40.00")
