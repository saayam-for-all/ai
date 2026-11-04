"""News-snippet routing, validation and provider failure response contracts."""
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

import lambda_function as LF
from services import disaster_check as dc, disaster_news as news

pytestmark = pytest.mark.contract
NOW = datetime(2023, 2, 6, 12, tzinfo=timezone.utc)
SNIPPET = "A magnitude 7.8 earthquake struck near Gaziantep, Turkey on 2023-02-06T01:17:34Z."
POINT = {"latitude": 37.0662, "longitude": 37.3833}
FIXTURE = Path(__file__).parent / "fixtures/usgs/kahramanmaras_2023-02-06.geojson"


@pytest.fixture
def edges():
    with mock.patch.object(news.disaster_geocoding, "geocode_place", return_value=POINT) as geo:
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(FIXTURE.read_bytes())) as http:
            yield geo, http


@pytest.mark.parametrize("broken", ["geocoder", "feed"])
def test_provider_outage_preserves_502_without_all_clear_or_secrets(edges, broken, capsys):
    if broken == "geocoder":
        edges[0].side_effect = dc.DisasterCheckUnavailable("Geocoding unavailable")
    else:
        edges[1].side_effect = TimeoutError("secret-provider-details")
    with mock.patch.object(news, "datetime", wraps=datetime) as clock:
        clock.now.return_value = NOW
        result = LF.disaster_check_handler({"news_snippet": SNIPPET}, None)
    assert result["statusCode"] == 502
    assert result["body"]["code"] == "DISASTER_CHECK_UNAVAILABLE"
    assert "disaster_detected" not in result["body"]
    assert "secret-provider-details" not in json.dumps(result) + capsys.readouterr().out


@pytest.mark.parametrize("wrapper", [False, True])
def test_unified_router_forwards_snippet_and_returns_object_body(edges, wrapper):
    payload = {"service": "disaster_check", "news_snippet": SNIPPET}
    with mock.patch.object(news, "datetime", wraps=datetime) as clock:
        clock.now.return_value = NOW
        result = LF.lambda_handler({"body": json.dumps(payload)} if wrapper else payload, None)
    assert result["statusCode"] == 200
    assert isinstance(result["body"], dict)
    assert result["body"]["status"] == "matched"


@pytest.mark.parametrize("extra", [{"latitude": 1}, {"longitude": None}, POINT, {"radius_km": 1}, {"window_hours": 24}])
def test_mixed_query_is_rejected_before_provider_calls(edges, extra):
    result = LF.disaster_check_handler({"news_snippet": SNIPPET, **extra}, None)
    assert result["statusCode"] == 400
    assert not edges[0].called and not edges[1].called


def test_blank_snippet_cannot_silently_fall_through_to_coordinate_query(edges):
    result = LF.disaster_check_handler({"news_snippet": "", **POINT}, None)
    assert result["statusCode"] == 400
    assert not edges[1].called
