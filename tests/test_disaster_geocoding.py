"""Geocoding transport, ambiguity and credential isolation."""
import http.client
import io
import json
import urllib.error
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import pytest

from services import disaster_geocoding as geo
from services.disaster_check import DisasterCheckUnavailable

pytestmark = pytest.mark.unit
REAL_API_KEY = geo._api_key


@pytest.fixture(autouse=True)
def credentials():
    REAL_API_KEY.cache_clear()
    with mock.patch.object(geo, "_api_key", return_value="test-secret"):
        yield
    REAL_API_KEY.cache_clear()


def answer(payload):
    return mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(json.dumps(payload).encode()))


def test_unique_place_and_bounded_encoded_request():
    with answer([{"lat": "35.68", "lon": "139.69"}]) as http:
        assert geo.geocode_place("Tokyo & vicinity, Japan") == {"latitude": 35.68, "longitude": 139.69}
    request = http.call_args.args[0]
    url = urlsplit(request.full_url)
    assert url.scheme == "https" and url.netloc == "geocode.maps.co"
    assert parse_qs(url.query) == {"q": ["Tokyo & vicinity, Japan"], "format": ["json"], "limit": ["2"]}
    assert "test-secret" not in request.full_url
    assert request.get_header("Authorization") == "Bearer test-secret"
    assert http.call_args.kwargs["timeout"] == 4


@pytest.mark.parametrize("payload", [[], [{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}]])
def test_unknown_or_ambiguous_place_never_selects_first_result(payload):
    with answer(payload):
        assert geo.geocode_place("Springfield") is None


@pytest.mark.parametrize("payload", [{}, None, "", [{}], [{"lat": "nan", "lon": 2}],
    [{"lat": 91, "lon": 2}], [{"lat": 1, "lon": 181}], [{"lat": True, "lon": 2}],
    [{"lat": None, "lon": 2}], [{"lat": 1, "lon": "inf"}]])
def test_malformed_geocoding_is_an_outage_not_unknown_location(payload):
    with answer(payload), pytest.raises(DisasterCheckUnavailable):
        geo.geocode_place("Tokyo")


@pytest.mark.parametrize("failure", [TimeoutError("secret"), urllib.error.URLError("secret"),
    http.client.IncompleteRead(b"secret"),
    urllib.error.HTTPError("https://provider/secret", 429, "Slow down", {}, None),
    urllib.error.HTTPError("https://provider/secret", 503, "Unavailable", {}, None)])
def test_network_failures_are_sanitized_and_not_retried(failure):
    with mock.patch("urllib.request.urlopen", side_effect=failure) as http:
        with pytest.raises(DisasterCheckUnavailable) as error:
            geo.geocode_place("Tokyo")
    assert "secret" not in str(error.value)
    assert http.call_count == 1


def test_unreadable_json_is_unavailable():
    with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(b"<html>down</html>")):
        with pytest.raises(DisasterCheckUnavailable):
            geo.geocode_place("Tokyo")


def test_credentials_unavailable_does_not_send_http_request():
    with mock.patch.object(geo, "_api_key", side_effect=DisasterCheckUnavailable("Credentials unavailable")):
        with mock.patch("urllib.request.urlopen") as http, pytest.raises(DisasterCheckUnavailable):
            geo.geocode_place("Tokyo")
    assert not http.called


def test_key_is_loaded_lazily_from_parameter_store_and_cached(monkeypatch):
    monkeypatch.setenv("DISASTER_GEOCODING_KEY_PARAMETER", "/test/geocoding/key")
    client = mock.Mock()
    client.get_parameter.return_value = {"Parameter": {"Value": "ssm-secret"}}
    with mock.patch("boto3.client", return_value=client) as factory:
        assert REAL_API_KEY() == "ssm-secret"
        assert REAL_API_KEY() == "ssm-secret"
    client.get_parameter.assert_called_once_with(Name="/test/geocoding/key", WithDecryption=True)
    config = factory.call_args.kwargs["config"]
    assert config.connect_timeout == 2 and config.read_timeout == 2
    assert config.retries == {"total_max_attempts": 1}


@pytest.mark.parametrize("result", [{}, {"Parameter": {"Value": ""}}, {"Parameter": {"Value": None}}])
def test_missing_ssm_key_is_unavailable(result, monkeypatch):
    monkeypatch.delenv("DISASTER_GEOCODING_KEY_PARAMETER", raising=False)
    client = mock.Mock()
    client.get_parameter.return_value = result
    with mock.patch("boto3.client", return_value=client), pytest.raises(DisasterCheckUnavailable):
        REAL_API_KEY()
    assert client.get_parameter.call_args.kwargs["Name"] == geo.DEFAULT_KEY_PARAMETER


def test_ssm_errors_do_not_leak_credentials():
    with mock.patch("boto3.client", side_effect=RuntimeError("secret-aws-details")):
        with pytest.raises(DisasterCheckUnavailable) as error:
            REAL_API_KEY()
    assert "secret" not in str(error.value)
