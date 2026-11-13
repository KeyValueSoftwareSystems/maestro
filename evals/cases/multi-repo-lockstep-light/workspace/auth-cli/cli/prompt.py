"""Ask the person for the sign-in code they were sent."""

EXPECTED_LENGTH = 5


def read_code(raw):
    """The code typed by the person, or an error message to show them."""
    code = raw.strip().replace(" ", "")
    if len(code) != EXPECTED_LENGTH or not code.isdigit():
        return None, f"Enter the {EXPECTED_LENGTH}-digit code we sent you."
    return code, None
