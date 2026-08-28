"""
The no argument call to Emergency Contacts.

The deployed web client requests emergency numbers with no parameters, then
looks the result up by the user's own country name, which it holds in the
Cognito zoneinfo attribute:

    const P = await getEmergencyContact();   // no parameters
    const b = P.body[user.zoneinfo];         // "India", "United States", ...

So a parameterless call returns the whole directory keyed by country name.
Country names come from the client's own list, so they must match exactly.

No network or keys required.
"""
import json

import lambda_function as LF
from services.emergency import _COUNTRY_DISPLAY_NAMES, get_emergency_directory


def test_no_parameters_returns_a_directory_keyed_by_country_name():
    res = LF.emergency_contacts_handler({}, None)
    assert res["statusCode"] == 200
    body = res["body"]
    assert isinstance(body, dict), "client reads body[country], so it must be an object"
    assert "India" in body and "United States" in body


def test_india_returns_indian_numbers_not_us_ones():
    # This is the original P0: non US users were shown 911.
    body = LF.emergency_contacts_handler({}, None)["body"]
    india = body["India"]
    assert "112" in india, f"expected Indian police number, got {india!r}"
    assert "911" not in india, f"US number leaked into the India entry: {india!r}"


def test_entries_are_single_line_strings_the_client_can_render():
    # The client renders `${country}: ${value}` into one span, so the value
    # must be a string, not an object.
    body = LF.emergency_contacts_handler({}, None)["body"]
    for country, value in body.items():
        assert isinstance(value, str), f"{country} is {type(value).__name__}, not str"
        assert "\n" not in value


def test_entries_are_labelled_and_ordered_most_urgent_first():
    body = LF.emergency_contacts_handler({}, None)["body"]
    india = body["India"]
    assert india.startswith("Police "), india
    for label in ("Police", "Ambulance", "Fire"):
        assert label in india, f"{label} missing from {india!r}"


def test_every_country_in_the_data_has_a_display_name():
    # A missing name silently drops that country from the directory.
    data = json.load(open("services/emergency_numbers.json", encoding="utf-8"))
    missing = [c for c in data if c not in _COUNTRY_DISPLAY_NAMES]
    assert not missing, f"no display name for: {missing}"


def test_countries_with_no_usable_numbers_are_omitted_not_blank():
    body = get_emergency_directory()["body"]
    assert all(v.strip() for v in body.values())


def test_the_parameter_path_still_works():
    # Passing a country must keep returning the structured response.
    res = LF.emergency_contacts_handler({"queryStringParameters": {"country": "India"}}, None)
    assert res["statusCode"] == 200
    assert res["body"]["services"]["police"]["dial_number"] == "112"


def test_unknown_country_still_404s():
    res = LF.emergency_contacts_handler({"queryStringParameters": {"country": "Atlantis"}}, None)
    assert res["statusCode"] == 404
