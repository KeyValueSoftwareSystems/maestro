import unittest

from auth.otp import CODE_LENGTH, issue_code, verify_code


class OtpTest(unittest.TestCase):
    def test_issued_code_verifies_once(self):
        body, code = issue_code("+100")
        self.assertEqual((body["code_length"], len(code)), (CODE_LENGTH, CODE_LENGTH))
        self.assertTrue(verify_code("+100", code))
        self.assertFalse(verify_code("+100", code))

    def test_wrong_length_is_refused(self):
        _body, code = issue_code("+101")
        self.assertFalse(verify_code("+101", code + "0"))
