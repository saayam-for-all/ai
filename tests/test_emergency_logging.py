"""Logging for the Emergency Contacts Lambda (follow-up to issue #146).

The Frankfurt, Prague and Vienna reports could only be diagnosed from Lambda
durations: the location lookups failed silently and nothing recorded what the
caller had sent. These tests pin what each request now logs - what was sent,
how the location was found, why a lookup failed and what was returned - and
that exact coordinates, full IP addresses and login tokens never reach the log.
"""
import io
import json
import logging
import socket
import urllib.error
from unittest import mock

import pytest

# Logging of the emergency lookup: content, privacy and levels.
pytestmark = pytest.mark.unit

import lambda_function as LF
import services.emergency as em

LOGGER = em.logger.name
CALLER_IP = "74.102.193.3"
PRAGUE = {"address": {"city": "Praha", "postcode": "120 00", "country_code": "cz"}}
HOUSTON_IP = {"postal": "77001", "city": "Houston", "region": "Texas", "country": "US"}


@pytest.fixture(autouse=True)
def _shipped_data(monkeypatch):
    """Answer from the repository's file, never S3."""
    with open(em.DATA_FILE, encoding="utf-8") as f:
        monkeypatch.setattr(em, "_emergency_numbers_cache", json.load(f))


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    return caplog


def _fake_urlopen(*responses):
    """A urlopen stand-in answering each call with the next JSON payload.

    An exception in `responses` is raised instead, as a provider timeout or
    refusal would be.
    """
    queue = list(responses)

    def _open(req, timeout=None):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return io.BytesIO(json.dumps(item).encode("utf-8"))

    return _open


def _lookup(params, ip=CALLER_IP, *responses):
    with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen(*responses)):
        return em.get_emergency_services(params, ip)


def _http_error(code):
    return urllib.error.HTTPError("https://example.invalid", code, "error", None, None)


# -------------------------------------------------------------------------
# What a request logs
# -------------------------------------------------------------------------

def test_gps_request_logs_what_was_sent_how_it_was_found_and_what_came_back(logs):
    result = _lookup({"lat": "50.0755", "lng": "14.4378"}, CALLER_IP, PRAGUE)
    assert result["status"] == 200
    assert "emergency request: gps=True lat~50.1 lng~14.4" in logs.text
    assert "Nominatim reverse lookup: lat~50.1 lng~14.4 -> Praha, CZ" in logs.text
    assert "emergency response: status=200 country=CZ" in logs.text
    assert "source=gps" in logs.text
    assert "'police': '158'" in logs.text


def test_exact_coordinates_and_full_ip_never_reach_the_log(logs):
    _lookup({"lat": "50.0755", "lng": "14.4378"}, CALLER_IP, PRAGUE)
    assert "50.0755" not in logs.text and "14.4378" not in logs.text
    assert CALLER_IP not in logs.text
    assert "74.102.193.x" in logs.text


def test_gps_that_does_not_resolve_says_the_ip_was_used_instead(logs):
    """The Prague report: a position was sent, but the answer came from the IP."""
    result = _lookup({"lat": "50.0755", "lng": "14.4378"}, CALLER_IP,
                     socket.timeout("timed out"), HOUSTON_IP)
    assert result["status"] == 200 and result["body"]["country"] == "US"
    assert "Nominatim reverse lookup failed for lat~50.1 lng~14.4: timeout" in logs.text
    assert "GPS coordinates did not resolve to a country; using the caller's IP (74.102.193.x) instead" in logs.text
    assert "ipinfo lookup: ip=74.102.193.x -> Houston, Texas, US" in logs.text
    assert "source=ip" in logs.text


def test_a_rate_limited_lookup_is_named_as_one(logs):
    _lookup({"lat": "50.0755", "lng": "14.4378"}, CALLER_IP, _http_error(429), HOUSTON_IP)
    assert "HTTP 429 (rate limited)" in logs.text


def test_ip_only_request_is_logged_with_the_ip_as_its_source(logs):
    result = _lookup({}, CALLER_IP, HOUSTON_IP)
    assert result["status"] == 200
    assert "emergency request: gps=False lat~None lng~None" in logs.text
    assert "source=ip" in logs.text


def test_country_parameter_is_logged_as_the_source_without_any_lookup(logs):
    result = _lookup({"country": "IN"}, CALLER_IP)   # no responses: any network call fails
    assert result["status"] == 200
    assert "source=country_param" in logs.text


def test_place_search_without_a_match_is_logged(logs):
    _lookup({"zip": "00000"}, None, [])
    assert "Nominatim place search found no match for '00000'" in logs.text


def test_failed_place_search_is_logged_with_the_reason(logs):
    _lookup({"zip": "00000"}, None, _http_error(503))
    assert "Nominatim place search failed for '00000': HTTP 503" in logs.text


def test_ipinfo_answer_without_a_country_is_a_warning(logs):
    _lookup({}, CALLER_IP, {"ip": CALLER_IP, "bogon": True})
    assert any(r.levelno == logging.WARNING and "returned no country" in r.getMessage()
               for r in logs.records)


def test_a_position_with_no_country_is_a_warning(logs):
    """A point at sea: Nominatim answers, but with no country in it."""
    _lookup({"lat": "30.0", "lng": "-40.0"}, None, {"address": {}})
    assert "Nominatim reverse lookup for lat~30.0 lng~-40.0 returned no country" in logs.text


def test_every_parameter_name_is_logged_but_not_its_value(logs):
    """A client sending "latitude" instead of "lat" is visible as the reason GPS was ignored."""
    _lookup({"latitude": "50.0755", "longitude": "14.4378"}, None)
    assert "gps=False" in logs.text
    assert "params=['latitude', 'longitude']" in logs.text
    assert "50.0755" not in logs.text


def test_the_response_line_names_the_services_filled_with_the_general_number(logs):
    _lookup({"lat": "50.0755", "lng": "14.4378"}, CALLER_IP, PRAGUE)
    line = next(r.getMessage() for r in logs.records if "status=200" in r.getMessage())
    assert "general_fallback=112 for [" in line
    assert "'suicide_helpline'" in line and "'police'" not in line.split("general_fallback")[1]


def test_a_city_in_several_countries_is_logged_as_not_guessed(logs):
    data = {
        "AA": {"default": {}, "states": {"North": {"cities": {"Springfield": {}}}}},
        "BB": {"default": {}, "states": {"South": {"cities": {"Springfield": {}}}}},
    }
    assert em.LocationResolver(None)._infer_state_country_from_city("springfield", data) is None
    assert "city 'Springfield' is in the directory for 2 countries (AA, BB); not guessing which" in logs.text
    assert em.LocationResolver(None)._infer_state_country_from_city("atlantis", data) is None
    assert "Atlantis" not in logs.text   # an unknown city is simply not found, not reported as ambiguous


def test_a_handler_failure_prints_its_traceback(capsys):
    event = {"headers": {"Authorization": "Bearer SECRET-TOKEN-123"}, "queryStringParameters": {"country": "IN"}}
    with mock.patch.object(LF, "get_emergency_services", side_effect=RuntimeError("boom")):
        response = LF.emergency_contacts_handler(event, None)
    assert response["statusCode"] == 500
    out = capsys.readouterr().out
    assert "ERROR: emergency_contacts failed: RuntimeError: boom" in out
    assert "Traceback (most recent call last)" in out
    assert "SECRET-TOKEN-123" not in out


def test_an_invalid_caller_ip_is_logged_without_the_value(logs):
    _lookup({}, "not-an-ip")
    assert "client IP is not a valid address (invalid)" in logs.text
    assert "not-an-ip" not in logs.text


@pytest.mark.parametrize("lat, lng, message", [
    ("north", "east", "lat/lng are not numbers"),
    ("91", "0", "lat/lng out of range"),
])
def test_unusable_coordinates_are_logged(logs, lat, lng, message):
    _lookup({"lat": lat, "lng": lng}, None)
    assert message in logs.text


# -------------------------------------------------------------------------
# Why a 404 or a 500 happened
# -------------------------------------------------------------------------

@pytest.mark.parametrize("params, ip, responses, reason", [
    ({"lat": "50.0755", "lng": "14.4378"}, CALLER_IP,
     (socket.timeout("timed out"), OSError("timed out")), "no country could be resolved"),
    ({"country": "Atlantis"}, None, (), "no numbers for ATLANTIS"),
    ({"country": "IN", "service": "dragon_control"}, None, (), "no dragon_control number for IN"),
])
def test_a_404_logs_why(logs, params, ip, responses, reason):
    result = _lookup(params, ip, *responses)
    assert result["status"] == 404
    assert f"status=404 reason={reason}" in logs.text


def test_an_unexpected_error_is_logged_with_its_traceback(logs):
    with mock.patch.object(em.EmergencyServiceResolver, "load_data", side_effect=RuntimeError("boom")):
        result = em.get_emergency_services({"country": "IN"}, None)
    assert result["status"] == 500
    errors = [r for r in logs.records if r.levelno == logging.ERROR]
    assert errors and errors[0].exc_info
    assert "status=500 (RuntimeError)" in errors[0].getMessage()


def test_the_handler_never_logs_the_login_token(logs, capsys):
    event = {
        "headers": {"Authorization": "Bearer SECRET-TOKEN-123"},
        "queryStringParameters": {"country": "IN"},
        "requestContext": {"identity": {"sourceIp": CALLER_IP}},
    }
    response = LF.emergency_contacts_handler(event, None)
    assert response["statusCode"] == 200
    printed = capsys.readouterr()
    assert "SECRET-TOKEN-123" not in logs.text + printed.out + printed.err


def test_logging_does_not_change_the_response_the_web_client_reads():
    result = _lookup({"lat": "50.0755", "lng": "14.4378"}, CALLER_IP, PRAGUE)
    body = result["body"]
    assert set(body) == {"services", "language", "country", "match_level", "resolved_location", "client_ip"}
    assert set(body["resolved_location"]) == {"zip", "city", "state", "country"}


# -------------------------------------------------------------------------
# Levels and helpers
# -------------------------------------------------------------------------

def test_info_lines_are_emitted_even_though_the_root_logger_is_at_warning():
    """The Lambda runtime leaves root at WARNING; the module's own level must let INFO through."""
    assert em.logger.isEnabledFor(logging.INFO)


@pytest.mark.parametrize("name, level", [
    (None, logging.INFO), ("debug", logging.DEBUG), (" Warning ", logging.WARNING), ("nonsense", logging.INFO),
])
def test_log_level_comes_from_the_environment_and_a_typo_falls_back_to_info(name, level):
    assert em._log_level(name) == level


@pytest.mark.parametrize("ip, masked", [
    ("74.102.193.3", "74.102.193.x"),
    ("2001:db8:abcd:12::1", "2001:db8:abcd::/48"),
    ("garbage", "invalid"),
    (None, "none"),
    ("", "none"),
])
def test_ip_addresses_are_masked(ip, masked):
    assert em._mask_ip(ip) == masked


@pytest.mark.parametrize("error, reason", [
    (_http_error(429), "HTTP 429 (rate limited)"),
    (_http_error(503), "HTTP 503"),
    (urllib.error.URLError(socket.timeout("timed out")), "timeout"),
    (socket.timeout("timed out"), "timeout"),
    (TimeoutError(), "timeout"),
    (json.JSONDecodeError("Expecting value", "", 0), "response was not JSON"),
    (ValueError("bad"), "ValueError: bad"),
])
def test_lookup_failures_are_described_in_a_few_words(error, reason):
    assert em._lookup_failure_reason(error) == reason


def test_a_refused_connection_is_a_network_error():
    reason = em._lookup_failure_reason(urllib.error.URLError(ConnectionRefusedError("refused")))
    assert reason.startswith("network error (ConnectionRefusedError")


def test_location_description_skips_empty_parts():
    assert em._describe({"city": "Wien", "state": None, "country": "AT"}) == "Wien, AT"
    assert em._describe({}) == "unknown"
