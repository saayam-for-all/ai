import json
from pathlib import Path


DATA_FILE = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "emergency_numbers.json"
)


def _load_emergency_numbers() -> dict:
    with DATA_FILE.open(encoding="utf-8") as f:
        return json.load(f)

def lookup_emergency_number(country: str, service: str) -> str | None:
    """Return the default emergency number for a country and service."""
    if not isinstance(country, str) or not isinstance(service, str):
        return None

    country = country.strip().upper()
    service = service.strip().lower()

    data = _load_emergency_numbers()
    country_data = data.get(country)

    if not country_data:
        return None

    default_numbers = country_data.get("default", {})
    return default_numbers.get(service)