"""Conservative secret redaction for the local session-memory demo.

This is a defense-in-depth filter, not a complete privacy/DLP system.
"""

import re

_SECRET = re.compile(
    r"\b(password|passphrase|passcode|otp|one[- ]time[- ]code|pin|cvv|cvc|"
    r"api[-_ ]?key|access[-_ ]?token|auth[-_ ]?token)\b"
    r"\s*(?::|=|\bis\b)\s*['\"]?[^\s,;'\"]+",
    flags=re.IGNORECASE,
)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")


def redact_sensitive(text: str) -> str:
    """Redact commonly formatted secrets without keeping their values."""
    if not isinstance(text, str):
        raise ValueError("Memory text must be a string")
    result = _SECRET.sub("[REDACTED SECRET]", text)
    result = _CARD.sub("[REDACTED CARD NUMBER]", result)
    result = _SSN.sub("[REDACTED ID]", result)
    return result
