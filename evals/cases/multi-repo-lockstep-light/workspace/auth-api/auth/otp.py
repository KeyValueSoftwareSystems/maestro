"""One-time sign-in codes: issued, then verified once."""
import secrets

CODE_LENGTH = 5
_ISSUED = {}


def issue_code(phone):
    """POST /otp — issue a code for a phone number; the response tells the client its length."""
    code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))
    _ISSUED[phone] = code
    return {"code_length": CODE_LENGTH}, code


def verify_code(phone, code):
    """POST /otp/verify — True once for the code last issued to this phone."""
    if not isinstance(code, str) or len(code) != CODE_LENGTH or not code.isdigit():
        return False
    if _ISSUED.get(phone) != code:
        return False
    del _ISSUED[phone]
    return True
