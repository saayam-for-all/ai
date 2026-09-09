"""A worked example for Mission 4. It passes every check in the self
check, and it is wrong in at least three ways. That is deliberate.

Do not "fix" it. See worked_example/README.md."""
import json, os, re
def _dataset():
    """Find services/emergency_numbers.json whether this file sits at the repo
    root or one directory down. Reading is the point; running it should not
    depend on where you saved it."""
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.dirname(here)):
        path = os.path.join(base, "services", "emergency_numbers.json")
        if os.path.isfile(path):
            return json.load(open(path, encoding="utf-8"))
    raise FileNotFoundError("run this from a dev checkout; the dataset lives there")


_DATA = _dataset()

TOOL_SCHEMA = {
    "name": "lookup_emergency_number",
    "description": ("Look up the official emergency telephone number for one service "
                    "in one country. Use this whenever the user asks what to dial. "
                    "Country must be an ISO 3166-1 alpha-2 code such as JP or IN."),
    "parameters": {
        "type": "object",
        "properties": {
            "country": {"type": "string", "description": "ISO alpha-2 country code"},
            "service": {"type": "string",
                        "enum": ["police", "ambulance", "fire", "general_emergency"]},
        },
        "required": ["country", "service"],
    },
}

_CODE = re.compile(r"^[A-Z]{2}$")

def lookup_emergency_number(country, service):
    """Return the number, or None. Never raises on bad input."""
    if not isinstance(country, str) or not isinstance(service, str):
        return None
    country, service = country.strip().upper(), service.strip().lower()
    if not _CODE.match(country) or country not in _DATA:
        return None
    return _DATA[country].get("default", {}).get(service) or None
