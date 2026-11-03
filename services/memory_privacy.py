"""Conservative secret redaction for the local session-memory demo.

This is a defense-in-depth filter, not a complete privacy/DLP system.
"""

import re

# Secrets whose value can be any word (passwords may be all letters).
_SECRET = re.compile(
    r"\b(password|passphrase|passcode|"
    r"api[-_ ]?key|access[-_ ]?token|auth[-_ ]?token)\b"
    r"\s*(?::|=|\bis\b)\s*['\"]?[^\s,;'\"]+",
    flags=re.IGNORECASE,
)
# Numeric codes: the value must contain a digit, so ordinary prose such as
# "the otp is valid until 5pm" is left alone. "pin code" / "pincode" (the
# Indian postal code) never matches because "code" is not a separator.
# A bare "PIN: 560001" is still redacted: a six-digit UPI PIN looks the same
# as a postal code, and dropping a location fact costs less than storing a PIN.
_NUMERIC_SECRET = re.compile(
    r"\b(otp|one[- ]time[- ](?:code|password)|pin|cvv|cvc)\b"
    r"\s*(?::|=|\bis\b)\s*['\"]?[^\s,;'\"]*\d[^\s,;'\"]*",
    flags=re.IGNORECASE,
)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")


def redact_sensitive(text: str) -> str:
    """Redact commonly formatted secrets without keeping their values."""
    if not isinstance(text, str):
        raise ValueError("Memory text must be a string")
    result = _SECRET.sub("[REDACTED SECRET]", text)
    result = _NUMERIC_SECRET.sub("[REDACTED SECRET]", result)
    result = _CARD.sub("[REDACTED CARD NUMBER]", result)
    result = _SSN.sub("[REDACTED ID]", result)
    return result
