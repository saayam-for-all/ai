"""
Tests for #146 - Emergency Contacts must never fall back to US numbers (911/988)
for non-US or unknown locales. Runs against the real emergency_numbers.json.
No network: exercises EmergencyServiceResolver._find_services directly.
"""

import pytest

# Emergency Contacts resolution behaviour and numeral localisation.
pytestmark = pytest.mark.unit
import services.emergency as em

DATA = em._load_emergency_numbers()
R = em.EmergencyServiceResolver()
US_NUMBERS = {"911", "988"}


def find(location, service=None):
    return R._find_services(location, DATA, service)


def test_india_missing_service_uses_india_default_not_us():
    # Karnataka's state default has no suicide_helpline -> must descend to India's
    # country default (Indian helpline), NOT US 988.
    svc, level = find({"country": "IN", "state": "Karnataka"}, "suicide_helpline")
    assert svc is not None, "should resolve within India, not 404"
    assert svc["suicide_helpline"] not in US_NUMBERS, svc


def test_india_fire_is_indian_not_911():
    svc, _ = find({"country": "IN", "state": "Karnataka"}, "fire")
    assert svc and svc["fire"] not in US_NUMBERS, svc


def test_country_name_normalizes_to_iso():
    # Locale sent as "India" (name) instead of "IN" (code) is normalized -> Indian
    # numbers, NOT US and NOT "unavailable".
    svc, _ = find({"country": "India"}, "fire")
    assert svc and svc["fire"] not in US_NUMBERS, svc
    # case-insensitive alpha-2 too
    svc, _ = find({"country": "in"}, "fire")
    assert svc and svc["fire"] not in US_NUMBERS, svc


def test_truly_unknown_country_is_unavailable_not_us():
    # A country genuinely not in the dataset (name or bogus code) -> "unavailable",
    # never US numbers. We do not invent numbers we don't have.
    for country in ("Atlantis", "ZZ", "Wakanda"):
        for service in ("fire", "suicide_helpline", "police"):
            svc, _ = find({"country": country}, service)
            assert svc is None, f"{country}/{service}: {svc}"


def test_india_full_set_has_no_us_numbers():
    svc, _ = find({"country": "IN"})
    assert svc is not None
    assert not (US_NUMBERS & set(map(str, svc.values()))), svc


def test_us_still_works():
    svc, _ = find({"country": "US"}, "fire")
    assert svc and svc["fire"] == "911", svc


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
