"""location_source and display_location in the Emergency Contacts response.

Two points raised on webapp#1959 after the Frankfurt, Prague and Vienna
reports. The page could not tell a GPS position from a guess based on the
caller's IP (Prague showed Houston), and it assembled the area line itself
from city, state and country, printing "Wien, null (AT)" for a city-state.
The response now says how the location was found and carries a ready-to-show
English place name. Both are additions: every field the page already reads
keeps its name and shape.
"""
import io
import json
import socket
import urllib.parse
from unittest import mock

import pytest

# What the browser receives: these pin the response the web page reads.
pytestmark = pytest.mark.contract

import lambda_function as LF
import services.emergency as em

CALLER_IP = "203.0.113.45"

# Nominatim answers as given for these points with accept-language=en.
VIENNA = {"address": {"city": "Vienna", "postcode": "1010", "country_code": "at",
                      "ISO3166-2-lvl4": "AT-9"}}
OSAKA = {"address": {"city": "Osaka", "province": "Osaka Prefecture", "postcode": "530-0001",
                     "country_code": "jp"}}
BENGALURU = {"address": {"city": "Bengaluru", "state": "Karnataka", "postcode": "560001",
                         "country_code": "in"}}
HOUSTON_IP = {"postal": "77001", "city": "Houston", "region": "Texas", "country": "US"}


@pytest.fixture(autouse=True)
def _shipped_data(monkeypatch):
    """Answer from the repository's file, never S3."""
    with open(em.DATA_FILE, encoding="utf-8") as f:
        monkeypatch.setattr(em, "_emergency_numbers_cache", json.load(f))


def _lookup(params, *responses, ip=CALLER_IP):
    """Run one lookup; each outbound call gets the next payload (or raises it).

    Returns the response body and the URLs that were requested.
    """
    queue, urls = list(responses), []

    def _open(req, timeout=None):
        urls.append(getattr(req, "full_url", req))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return io.BytesIO(json.dumps(item).encode("utf-8"))

    with mock.patch("urllib.request.urlopen", side_effect=_open):
        result = em.get_emergency_services(params, ip)
    return result, urls


# -------------------------------------------------------------------------
# location_source: how the location was found
# -------------------------------------------------------------------------

def test_a_resolved_gps_position_is_reported_as_gps():
    result, _ = _lookup({"lat": "48.2082", "lng": "16.3738"}, VIENNA)
    assert result["status"] == 200
    assert result["body"]["location_source"] == "gps"
    assert result["body"]["services"]["police"]["dial_number"] == "133"


def test_gps_that_did_not_resolve_is_reported_as_an_ip_estimate():
    """The Prague report: the browser sent a position, the answer came from the IP.

    The page cannot see this from its side (it did send GPS), so only
    location_source tells it the area shown is an estimate.
    """
    result, _ = _lookup({"lat": "50.0755", "lng": "14.4378"},
                        socket.timeout("timed out"), HOUSTON_IP)
    body = result["body"]
    assert body["location_source"] == "ip"
    assert body["country"] == "US"
    assert body["display_location"] == "Houston, Texas (US)"


def test_a_position_with_no_country_falls_back_to_the_ip():
    """A point at sea: Nominatim answers, but with no country.

    The empty keys it left used to block the IP's answer, so the caller got a
    404 although their IP gave a country.
    """
    result, urls = _lookup({"lat": "30.0", "lng": "-40.0"}, {"address": {}}, HOUSTON_IP)
    assert len(urls) == 2   # Nominatim, then ipinfo
    body = result["body"]
    assert result["status"] == 200 and body["country"] == "US"
    assert body["location_source"] == "ip"
    assert body["resolved_location"] == {"zip": "77001", "city": "Houston", "state": "Texas", "country": "US"}
    assert body["display_location"] == "Houston, Texas (US)"


def test_an_ip_answer_replaces_everything_the_gps_answer_left():
    """Nothing from a GPS answer without a country survives into the IP's result:
    not its region (a name mixing two sources), not its empty keys."""
    gps_no_country = {"address": {"province": "Atlantic Province"}}
    result, _ = _lookup({"lat": "30.0", "lng": "-40.0"}, gps_no_country, {"country": "DE"})
    body = result["body"]
    assert body["resolved_location"] == {"country": "DE"}   # the IP gave only a country
    assert body["display_location"] == "DE"


def test_a_request_without_gps_is_reported_as_an_ip_estimate():
    result, _ = _lookup({}, HOUSTON_IP)
    assert result["body"]["location_source"] == "ip"


def test_a_country_parameter_alone_is_reported_as_country_param():
    result, urls = _lookup({"country": "IN"})
    assert urls == []   # no lookup was needed
    assert result["body"]["location_source"] == "country_param"
    assert result["body"]["display_location"] == "IN"


def test_a_country_parameter_that_confirms_the_gps_result_keeps_gps():
    result, _ = _lookup({"lat": "48.2082", "lng": "16.3738", "country": "AT"}, VIENNA)
    assert result["body"]["location_source"] == "gps"
    assert result["body"]["display_location"] == "Vienna (AT)"


def test_a_country_parameter_that_overrides_the_gps_result_is_reported_as_country_param():
    result, _ = _lookup({"lat": "34.6937", "lng": "135.5023", "country": "IN"}, OSAKA)
    body = result["body"]
    assert body["location_source"] == "country_param"
    assert body["country"] == "IN"
    # Nothing from Osaka survives into the name or the location.
    assert body["display_location"] == "IN"
    assert body["resolved_location"] == {"country": "IN"}


def test_a_place_search_is_reported_as_place():
    search = [{"lat": "12.9784", "lon": "77.5996"}]
    result, _ = _lookup({"zip": "560001"}, search, BENGALURU)
    body = result["body"]
    assert body["location_source"] == "place"
    assert body["match_level"] == "zip"
    assert body["display_location"] == "Bengaluru, Karnataka (IN)"


def test_a_city_found_only_in_the_directory_is_reported_as_city_directory():
    result, _ = _lookup({"city": "mysuru"}, socket.timeout("timed out"), ip=None)
    body = result["body"]
    assert body["location_source"] == "city_directory"
    assert body["display_location"] == "Mysuru, Karnataka (IN)"


def test_a_404_body_is_unchanged():
    result, _ = _lookup({"country": "Atlantis"}, ip=None)
    assert result == {"status": 404, "body": {"error": "Emergency services not found"}}


def test_a_position_that_found_no_country_is_logged_with_source_none(caplog):
    caplog.set_level("INFO", logger=em.logger.name)
    result, _ = _lookup({"lat": "30.0", "lng": "-40.0"}, {"error": "Unable to geocode"}, ip=None)
    assert result["status"] == 404
    assert "status=404 reason=no country could be resolved source=none" in caplog.text


# -------------------------------------------------------------------------
# display_location: a place name the page can show as is
# -------------------------------------------------------------------------

def test_a_city_state_reads_without_null():
    """Vienna has no separate state; the old page printed "Wien, null (AT)"."""
    result, _ = _lookup({"lat": "48.2082", "lng": "16.3738"}, VIENNA)
    body = result["body"]
    assert body["display_location"] == "Vienna (AT)"
    assert "null" not in body["display_location"].lower()
    assert body["resolved_location"]["state"] is None   # the old field is untouched


def test_a_prefecture_given_as_province_is_used_for_the_name_only():
    result, _ = _lookup({"lat": "34.6937", "lng": "135.5023"}, OSAKA)
    body = result["body"]
    assert body["display_location"] == "Osaka, Osaka Prefecture (JP)"
    # resolved_location keeps its four keys; province is not added to it.
    assert body["resolved_location"] == {"zip": "530-0001", "city": "Osaka", "state": None, "country": "JP"}


@pytest.mark.parametrize("key", ["province", "region", "state_district"])
def test_a_region_given_under_another_key_is_used_for_the_name(key):
    answer = {"address": {"city": "Somewhere", key: "Some Region", "country_code": "jp"}}
    result, _ = _lookup({"lat": "35.0", "lng": "139.0"}, answer)
    assert result["body"]["display_location"] == "Somewhere, Some Region (JP)"
    assert result["body"]["resolved_location"]["state"] is None


def test_a_municipality_is_used_when_there_is_no_city_town_or_village():
    answer = {"address": {"municipality": "Hakone", "province": "Kanagawa Prefecture", "country_code": "jp"}}
    result, _ = _lookup({"lat": "35.2", "lng": "139.0"}, answer)
    body = result["body"]
    assert body["display_location"] == "Hakone, Kanagawa Prefecture (JP)"
    assert body["resolved_location"]["city"] is None   # resolved_location is not changed


def test_a_real_state_and_city_win_over_the_other_keys():
    """The other keys only fill a gap: a district or municipality never
    replaces a state or city Nominatim did give."""
    answer = {"address": {"village": "Hosahalli", "state_district": "Mandya", "state": "Karnataka",
                          "country_code": "in"}}
    result, _ = _lookup({"lat": "12.5", "lng": "76.5"}, answer)
    assert result["body"]["display_location"] == "Hosahalli, Karnataka (IN)"
    answer = {"address": {"city": "Bergen", "municipality": "Bergen Municipality", "country_code": "no"}}
    result, _ = _lookup({"lat": "60.39", "lng": "5.32"}, answer)
    assert result["body"]["display_location"] == "Bergen (NO)"


def test_a_resolver_used_twice_does_not_carry_names_over():
    """One resolver per request in production; this keeps resolve() self-contained anyway."""
    resolver = em.LocationResolver(None)
    with mock.patch("urllib.request.urlopen",
                    side_effect=lambda req, timeout=None: io.BytesIO(json.dumps(OSAKA).encode())):
        resolver.resolve({"lat": "34.6937", "lng": "135.5023"}, em._emergency_numbers_cache)
    assert resolver.display_hint["region"] == "Osaka Prefecture"
    location = resolver.resolve({"country": "IN"}, em._emergency_numbers_cache)
    assert resolver.display_hint == {}
    assert em._display_location(location, resolver.display_hint) == "IN"


def test_both_nominatim_lookups_ask_for_english_names():
    search = [{"lat": "12.9784", "lon": "77.5996"}]
    _, urls = _lookup({"zip": "560001"}, search, BENGALURU)
    assert [urllib.parse.urlsplit(u).path for u in urls] == ["/search", "/reverse"]
    for url in urls:
        assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["accept-language"] == ["en"]


@pytest.mark.parametrize("location, hint, expected", [
    ({"city": "Vienna", "state": None, "country": "AT"}, None, "Vienna (AT)"),
    ({"city": "City of Westminster", "state": "England", "country": "GB"}, None,
     "City of Westminster, England (GB)"),
    ({"city": "Doha", "state": "Doha", "country": "QA"}, None, "Doha (QA)"),
    ({"city": "Berlin", "state": "berlin", "country": "DE"}, None, "Berlin (DE)"),
    ({"city": "Singapore", "country": "SG"}, None, "Singapore (SG)"),
    ({"city": "Osaka", "state": None, "country": "JP"}, {"region": "Osaka Prefecture"},
     "Osaka, Osaka Prefecture (JP)"),
    ({"city": None, "state": "Tokyo", "country": "JP"}, {"city": "Shinjuku"}, "Shinjuku, Tokyo (JP)"),
    ({"city": "  ", "state": "", "country": "in"}, None, "IN"),
    ({"country": "IN"}, None, "IN"),
    ({"city": "Atlantis"}, None, "Atlantis"),
    ({}, None, None),
])
def test_display_location_uses_only_the_parts_that_exist(location, hint, expected):
    assert em._display_location(location, hint) == expected


# -------------------------------------------------------------------------
# A JSON body with values that are not text
# -------------------------------------------------------------------------

@pytest.mark.parametrize("value", [["a", "b"], {"k": "v"}, True, False])
@pytest.mark.parametrize("field", ["zip", "city", "state", "country", "service", "language"])
def test_a_json_value_that_is_not_text_is_treated_as_not_sent(field, value):
    """Only a JSON body can carry these types. A list or object used to raise
    (city.title(), or a list as a dict key) and turn the lookup into a 500."""
    body = {field: value} if field == "country" else {field: value, "country": "IN"}
    event = {"body": json.dumps(body), "requestContext": {"identity": {"sourceIp": CALLER_IP}}}
    with mock.patch("urllib.request.urlopen",
                    side_effect=lambda req, timeout=None: io.BytesIO(json.dumps(HOUSTON_IP).encode())):
        response = LF.emergency_contacts_handler(event, None)
    assert response["statusCode"] == 200, response
    answer = json.loads(response["body"])
    # Answered as if the field had not been sent.
    assert answer["country"] == ("US" if field == "country" else "IN")
    assert answer["location_source"] == ("ip" if field == "country" else "country_param")


def test_a_number_where_text_belongs_is_read_as_text():
    search = [{"lat": "12.9784", "lon": "77.5996"}]
    result, _ = _lookup({"zip": 560001, "country": "IN"}, search, BENGALURU, ip=None)
    assert result["status"] == 200 and result["body"]["match_level"] == "zip"
    result, _ = _lookup({"city": 12345, "country": "IN"}, [], ip=None)   # used to raise in city.title()
    assert result["status"] == 200


# -------------------------------------------------------------------------
# The web page keeps working
# -------------------------------------------------------------------------

def test_the_response_only_adds_the_two_fields():
    """Every field the page already reads keeps its name and shape."""
    result, _ = _lookup({"lat": "48.2082", "lng": "16.3738"}, VIENNA)
    body = result["body"]
    assert set(body) == {"services", "language", "country", "match_level", "resolved_location",
                         "client_ip", "location_source", "display_location"}
    assert set(body["resolved_location"]) == {"zip", "city", "state", "country"}
    assert set(body["services"]["police"]) == {"dial_number", "display_number", "source", "is_fallback"}


def test_the_lambda_handler_returns_both_fields_through_api_gateway():
    event = {
        "queryStringParameters": {"lat": "48.2082", "lng": "16.3738"},
        "requestContext": {"identity": {"sourceIp": CALLER_IP}},
    }
    with mock.patch("urllib.request.urlopen",
                    side_effect=lambda req, timeout=None: io.BytesIO(json.dumps(VIENNA).encode())):
        response = LF.emergency_contacts_handler(event, None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])   # proxy integration: the body is a string
    assert body["location_source"] == "gps"
    assert body["display_location"] == "Vienna (AT)"
