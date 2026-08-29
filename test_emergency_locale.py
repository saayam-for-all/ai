"""Behaviour tests for issue #146 - Emergency Contacts must never show a user a
number from another country, and must never leave a field empty for the web
client to fill with a hardcoded US default (911 / 988).

Runs against the real services/emergency_numbers.json. No network and no keys:
every case supplies an explicit country, which short-circuits geocoding and the
IP lookup.
"""
import json
from unittest import mock

import pytest

import services.emergency as em

DATA = em._load_emergency_numbers()
R = em.EmergencyServiceResolver()

US_NUMBERS = {"911", "988"}
COUNTRIES = sorted(DATA)


def find(location, service=None):
    return R._find_services(location, DATA, service)


def numbers_in_country_record(country_code):
    """Every number that appears anywhere under one country's record."""
    found = set()

    def collect(services):
        found.update(str(v).strip() for v in (services or {}).values())

    country = DATA[country_code]
    collect(country.get("default"))
    for state in country.get("states", {}).values():
        collect(state.get("default"))
        for bucket in ("cities", "zips"):
            for services in state.get(bucket, {}).values():
                collect(services)
    return found


# -------------------------------------------------------------------------
# The reported symptoms
# -------------------------------------------------------------------------

def test_india_fire_is_indian_not_911():
    """Reported symptom 1: the India Fire row showed US 911."""
    svc, _ = find({"country": "IN", "state": "Karnataka"}, "fire")
    assert svc, "fire must resolve for India, not come back unavailable"
    assert svc["fire"]["number"] == "101"


def test_india_mental_health_is_indian_not_988():
    """Reported symptom 2: the India Mental Health row showed US 988."""
    svc, _ = find({"country": "IN", "state": "Karnataka"}, "suicide_helpline")
    assert svc
    assert svc["suicide_helpline"]["number"] not in US_NUMBERS, svc


@pytest.mark.parametrize(
    "service,expected",
    [
        ("general_emergency", "112"),   # Pan-India emergency
        ("police", "112"),
        ("fire", "101"),
        ("ambulance", "108"),
        ("disaster_management", "108"),
        ("women_helpline", "1091"),
    ],
)
def test_india_returns_the_routes_the_ticket_asks_for(service, expected):
    svc, _ = find({"country": "IN"}, service)
    assert svc and svc[service]["number"] == expected, svc


def test_india_full_directory_has_no_us_numbers():
    svc, _ = find({"country": "IN"})
    dialled = {k: v["number"] for k, v in svc.items()}
    assert not US_NUMBERS & set(dialled.values()), dialled


# -------------------------------------------------------------------------
# The invariant, swept across the whole dataset
# -------------------------------------------------------------------------

def test_no_response_ever_contains_a_foreign_number():
    """Every number returned for a country appears in that country's own record.

    This is the general form of the bug. Not "911 must not appear" - 911 is the
    real emergency number in Canada, Mexico, Argentina, Peru, the Philippines,
    Saudi Arabia, Venezuela and Ethiopia - but "nothing may be borrowed from
    another country's record".
    """
    borrowed = []
    for country in COUNTRIES:
        own = numbers_in_country_record(country)
        svc, _ = find({"country": country})
        assert svc, f"{country} resolved to nothing at all"
        borrowed += [
            f"{country}.{service} = {entry['number']}"
            for service, entry in svc.items()
            if entry["number"] not in own
        ]
    assert not borrowed, "numbers borrowed from another country:\n  " + "\n  ".join(borrowed)


def test_every_country_answers_every_modelled_service():
    """No modelled service comes back empty for a country we know.

    An empty field is what the web client papers over with 911 / 988, so
    closing the gap here removes the client's opportunity to do it.
    """
    gaps = []
    for country in COUNTRIES:
        for service in em.KNOWN_SERVICES:
            svc, _ = find({"country": country}, service)
            if not svc or not em.is_dialable(svc[service]["number"]):
                gaps.append(f"{country}.{service} -> {svc}")
    assert not gaps, "services that came back unavailable:\n  " + "\n  ".join(gaps)


def test_no_non_us_country_ever_shows_988():
    """988 is the one number in the dataset that is unambiguously US-only."""
    leaks = []
    for country in COUNTRIES:
        if country == "US":
            continue
        svc, _ = find({"country": country})
        leaks += [f"{country}.{s}" for s, e in svc.items() if e["number"] == "988"]
    assert not leaks, f"US suicide line shown outside the US: {leaks}"


# -------------------------------------------------------------------------
# Fallback behaviour
# -------------------------------------------------------------------------

def test_missing_service_falls_back_to_the_countrys_own_general_line():
    # Germany has no suicide_helpline on record. The fallback is 112, Germany's
    # own pan-emergency number, not the US 988.
    svc, _ = find({"country": "DE"}, "suicide_helpline")
    assert svc["suicide_helpline"]["number"] == "112"
    assert svc["suicide_helpline"]["source"] == em.SOURCE_GENERAL_FALLBACK


def test_a_fallback_is_labelled_as_one():
    """A general emergency line must not be passed off as the real service.

    The client needs to be able to say "general emergency line" instead of
    presenting 112 as a dedicated women's helpline.
    """
    svc, _ = find({"country": "FR"})
    assert svc["police"]["source"] == em.SOURCE_DIRECTORY
    assert svc["women_helpline"]["source"] == em.SOURCE_GENERAL_FALLBACK


def test_a_real_entry_is_never_overwritten_by_the_fallback():
    svc, _ = find({"country": "IN"})
    for service in ("police", "ambulance", "fire", "women_helpline",
                    "disaster_management", "suicide_helpline"):
        assert svc[service]["source"] == em.SOURCE_DIRECTORY, service


def test_unmodelled_service_is_unavailable_not_the_general_line():
    """Asking for something we do not model must not be answered with 112."""
    for service in ("pizza", "poison_control", "coast_guard", "  "):
        svc, _ = find({"country": "IN"}, service)
        assert svc is None, f"{service!r} was answered with {svc}"


def test_no_service_filter_returns_the_whole_directory():
    """An absent or blank service parameter means "give me everything"."""
    for service in (None, ""):
        svc, _ = find({"country": "IN"}, service)
        assert set(svc) == set(em.KNOWN_SERVICES), service


def test_city_entry_inherits_the_services_it_does_not_list():
    """Bengaluru lists only police and ambulance.

    Before this change the full-directory response for Bengaluru contained
    exactly those two, so Fire arrived empty at the client and became 911. The
    city entry now inherits fire from the Karnataka / India levels above it.
    """
    svc, level = find({"country": "IN", "state": "Karnataka", "city": "Bengaluru"})
    assert level == "city"
    assert svc["fire"]["number"] == "101"
    assert svc["fire"]["source"] == em.SOURCE_DIRECTORY
    # and the city's own, more specific values still win
    assert svc["police"]["number"] == "112"


def test_single_service_reports_the_level_it_actually_came_from():
    """Bengaluru matches at city level but does not list a fire number.

    The fire number comes from Karnataka, so that is what the match level says.
    Reporting "city" here would suggest a precision the answer does not have.
    """
    location = {"country": "IN", "state": "Karnataka", "city": "Bengaluru"}
    _svc, level = find(location, "police")
    assert level == "city"               # Bengaluru lists police itself
    _svc, level = find(location, "fire")
    assert level == "state"              # inherited from Karnataka
    _svc, level = find(location, "women_helpline")
    assert level == "country"            # only India's default has it


def test_more_specific_levels_override_broader_ones():
    fake = {
        "XX": {
            "default": {"police": "1", "fire": "11"},
            "states": {
                "S": {
                    "default": {"police": "22"},
                    "cities": {"C": {"police": "33"}},
                    "zips": {"99999": {"police": "44"}},
                }
            },
        }
    }
    svc, level = R._find_services({"country": "XX", "state": "S"}, fake)
    assert (svc["police"]["number"], level) == ("22", "state")

    svc, level = R._find_services({"country": "XX", "state": "S", "city": "C"}, fake)
    assert (svc["police"]["number"], level) == ("33", "city")

    svc, level = R._find_services(
        {"country": "XX", "state": "S", "city": "C", "zip": "99999"}, fake
    )
    assert (svc["police"]["number"], level) == ("44", "zip")
    # fire is only at country level and still comes through at every depth
    assert svc["fire"]["number"] == "11"


def test_country_with_no_dialable_number_at_all_is_unavailable():
    """We report nothing rather than invent a fallback out of nothing."""
    fake = {"XX": {"default": {"police": "", "fire": "unknown"}, "states": {}}}
    assert R._find_services({"country": "XX"}, fake) == (None, None)
    assert R._find_services({"country": "XX"}, fake, "fire") == (None, None)


# -------------------------------------------------------------------------
# Country resolution
# -------------------------------------------------------------------------

def test_country_name_normalizes_to_iso():
    for value in ("India", "india", "IN", "in", "Bharat"):
        svc, _ = find({"country": value}, "fire")
        assert svc and svc["fire"]["number"] == "101", value


def test_truly_unknown_country_is_unavailable_not_us():
    """A country we do not have is answered "unavailable", never with US numbers.

    We do not invent numbers we do not hold, and we do not borrow a neighbour's.
    """
    for country in ("Atlantis", "ZZ", "Wakanda", "  ", None):
        for service in ("fire", "suicide_helpline", "police", None):
            svc, _ = find({"country": country}, service)
            assert svc is None, f"{country}/{service}: {svc}"


def test_us_still_works():
    svc, _ = find({"country": "US", "state": "California"}, "fire")
    assert svc["fire"]["number"] == "911"
    svc, _ = find({"country": "US"}, "suicide_helpline")
    assert svc["suicide_helpline"]["number"] == "988"


def test_a_foreign_state_name_does_not_leak_into_another_country():
    """"Karnataka" under "US" must not match anything US-side."""
    svc, level = find({"country": "US", "state": "Karnataka"})
    assert level == "country"
    assert svc["police"]["number"] == "911"


def test_explicit_country_discards_a_contradicting_geocode():
    resolver = em.LocationResolver(client_ip=None)
    with mock.patch.object(
        resolver, "_reverse_geocode",
        return_value={"country": "IN", "state": "Karnataka", "city": "Bengaluru", "zip": "560001"},
    ):
        location = resolver.resolve(
            {"lat": "12.97", "lng": "77.59", "country": "US"}, DATA
        )
    assert location == {"country": "US"}, location


def test_agreeing_country_override_keeps_the_finer_detail():
    resolver = em.LocationResolver(client_ip=None)
    with mock.patch.object(
        resolver, "_reverse_geocode",
        return_value={"country": "IN", "state": "Karnataka", "city": "Bengaluru", "zip": None},
    ):
        location = resolver.resolve(
            {"lat": "12.97", "lng": "77.59", "country": "India"}, DATA
        )
    assert location["country"] == "IN"
    assert location["city"] == "Bengaluru"


def test_ambiguous_bare_city_is_not_guessed():
    """A city name in two countries must not pick one of them."""
    fake = {
        "AA": {"default": {"police": "1"}, "states": {"S": {"cities": {"Springfield": {"police": "1"}}, "zips": {}}}},
        "BB": {"default": {"police": "2"}, "states": {"T": {"cities": {"Springfield": {"police": "2"}}, "zips": {}}}},
    }
    resolver = em.LocationResolver(client_ip=None)
    assert resolver._infer_state_country_from_city("Springfield", fake) is None
    # unambiguous still resolves
    assert resolver._infer_state_country_from_city("Bengaluru", DATA)["country"] == "IN"


# -------------------------------------------------------------------------
# Input hardening
# -------------------------------------------------------------------------

@pytest.mark.parametrize(
    "number,expected",
    [
        ("112", True), ("000", True), ("10 111", True), ("+1-800-273-8255", True),
        ("115 and 1122", False),        # prose, not dialable
        ("0", False),                   # a lost leading zero
        ("", False), ("   ", False), ("unknown", False),
        (None, False), (911, False), (["112"], False),
        ("1" * 21, False),              # implausibly long
    ],
)
def test_is_dialable(number, expected):
    assert em.is_dialable(number) is expected


@pytest.mark.parametrize(
    "ip", ["evil.example.com", "1.2.3.4/../../admin", "", "  ", None, "999.1.1.1"],
)
def test_a_non_ip_is_never_put_into_the_lookup_url(ip):
    """The IP comes from a request header, so it is validated before use."""
    resolver = em.LocationResolver(client_ip=ip)
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call")):
        assert resolver._get_location_from_ip(ip) == {}


@pytest.mark.parametrize(
    "lat,lng",
    [("abc", "1.0"), ("1.0", "xyz"), ("91", "0"), ("0", "181"), (None, None), ("", "")],
)
def test_out_of_range_coordinates_are_rejected_before_any_request(lat, lng):
    resolver = em.LocationResolver(client_ip=None)
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call")):
        assert resolver._reverse_geocode(lat, lng) is None


# -------------------------------------------------------------------------
# Localization
# -------------------------------------------------------------------------

def test_display_number_is_localized_but_dial_number_stays_ascii():
    result = em.LocalizationService().localize_services(
        {"police": {"number": "112", "source": em.SOURCE_DIRECTORY}}, "hi"
    )
    assert result["police"]["dial_number"] == "112", "the dialed value must stay ASCII"
    assert result["police"]["display_number"] == "११२"
    assert result["police"]["is_fallback"] is False


def test_unknown_language_falls_back_to_the_ascii_digits():
    result = em.LocalizationService().localize_services(
        {"police": {"number": "112", "source": em.SOURCE_GENERAL_FALLBACK}}, "xx"
    )
    assert result["police"]["display_number"] == "112"
    assert result["police"]["is_fallback"] is True


# -------------------------------------------------------------------------
# End to end through get_emergency_services
# -------------------------------------------------------------------------

def test_end_to_end_india_response():
    result = em.get_emergency_services({"country": "India", "language": "hi"}, None)
    assert result["status"] == 200
    body = result["body"]
    assert body["country"] == "IN"
    dialled = {k: v["dial_number"] for k, v in body["services"].items()}
    assert dialled["fire"] == "101"
    assert dialled["general_emergency"] == "112"
    assert not US_NUMBERS & set(dialled.values()), dialled
    assert body["services"]["fire"]["display_number"] == "१०१"


def test_end_to_end_unknown_country_is_404_not_us_numbers():
    result = em.get_emergency_services({"country": "Atlantis"}, None)
    assert result["status"] == 404
    assert "911" not in json.dumps(result["body"])


def test_end_to_end_with_nothing_to_go_on_is_404():
    """No parameters and no client IP: we say we do not know."""
    result = em.get_emergency_services({}, None)
    assert result["status"] == 404


def test_missing_language_defaults_to_english():
    result = em.get_emergency_services({"country": "IN", "language": None}, None)
    assert result["body"]["language"] == "en"
    assert result["body"]["services"]["police"]["display_number"] == "112"
