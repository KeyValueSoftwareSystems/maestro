import unittest

from cli.prompt import EXPECTED_LENGTH, read_code


class PromptTest(unittest.TestCase):
    def test_accepts_a_code_of_the_expected_length(self):
        self.assertEqual(read_code(" 1 2 3 4 5 "), ("12345", None))

    def test_refuses_a_short_code(self):
        code, error = read_code("12")
        self.assertIsNone(code)
        self.assertIn(f"{EXPECTED_LENGTH}-digit", error)
