import unittest

from notes.titles import format_title


class TitleTest(unittest.TestCase):
    def test_plain_title_is_unchanged(self):
        self.assertEqual(format_title("Groceries"), "Groceries")


if __name__ == "__main__":
    unittest.main()
