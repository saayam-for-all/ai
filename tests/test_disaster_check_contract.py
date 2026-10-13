"""The disaster_check contract: the Lambda event in, the envelope out - issue #191.

These run the whole coordinate path - router, handler, selection, the USGS
adapter - against two responses recorded from the live feed, with only the
network edge replaced. They pin the acceptance criteria this slice covers:

    a location inside a known event    -> disaster_detected: true, with a
                                          USGS record in verified_by
    a location with nothing happening  -> disaster_detected: false, from one
                                          feed call
    the feed unreachable               -> DISASTER_CHECK_UNAVAILABLE, and no
                                          disaster_detected field at all

The body stays an object on every path, per #170: the web client reads
``response.body.<field>`` on non-proxy integration.
"""
import io
import json
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

import lambda_function as LF

pytestmark = pytest.mark.contract

FIXTURES = Path(__file__).parent / "fixtures" / "usgs"

# Gaziantep, about 35 km from the M7.8 epicentre of 6 February 2023.
GAZIANTEP = {"latitude": 37.0662, "longitude": 37.3833}

EVENT_FIELDS = {
    "event_id", "event_type", "severity", "headline", "started_at", "expires_at",
    "impact_zone", "impact_zone_fallback", "boundary_source", "verified_by",
    "llm_cross_check", "volunteer_band_km", "advisory",
}


def _feed_answers(name):
    body = (FIXTURES / name).read_bytes()
    return mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(body))


def _feed_is_down():
    return mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route to host"))


def _call(payload):
    return LF.disaster_check_handler({"body": json.dumps(payload)}, None)


# -------------------------------------------------------------------------
# A location inside a known event
# -------------------------------------------------------------------------

def test_a_location_inside_a_known_earthquake_is_detected():
    with _feed_answers("kahramanmaras_2023-02-06.geojson"):
        res = _call(GAZIANTEP)

    assert res["statusCode"] == 200
    body = res["body"]
    assert isinstance(body, dict), "body must not be serialised to a string"
    assert body["disaster_detected"] is True
    assert body["confidence"] == "high"

    mainshock = body["events"][0]
    assert mainshock["event_id"] == "usgs-us6000jllz"
    assert mainshock["event_type"] == "earthquake"
    assert mainshock["severity"] == "extreme"
    assert mainshock["started_at"] == "2023-02-06T01:17:34Z"


def test_every_event_carries_every_field_of_the_contract():
    with _feed_answers("kahramanmaras_2023-02-06.geojson"):
        events = _call(GAZIANTEP)["body"]["events"]

    assert len(events) > 1
    for event in events:
        assert set(event) == EVENT_FIELDS, event["event_id"]


def test_every_detection_is_backed_by_an_authoritative_source():
    """No event may reach a caller without the record that confirms it."""
    with _feed_answers("kahramanmaras_2023-02-06.geojson"):
        events = _call(GAZIANTEP)["body"]["events"]

    for event in events:
        (evidence,) = event["verified_by"]
        assert evidence["source"] == "USGS"
        assert evidence["url"].startswith("https://earthquake.usgs.gov/earthquakes/eventpage/")
        assert evidence["retrieved_at"].endswith("Z")
        # No model runs on this path, and the response must not imply one did.
        assert event["llm_cross_check"] is None


def test_every_zone_says_it_is_modelled():
    with _feed_answers("kahramanmaras_2023-02-06.geojson"):
        events = _call(GAZIANTEP)["body"]["events"]

    for event in events:
        assert event["boundary_source"] == "modelled"
        assert event["impact_zone"]["type"] == "Polygon"
        (ring,) = event["impact_zone"]["coordinates"]
        assert ring[0] == ring[-1]
        latitude, longitude = event["impact_zone_fallback"]["center"]
        # The epicentres are near 37-38 N, 36-38 E - close enough to make a
        # swapped pair pass a range check, so compare against the ring.
        assert min(p[1] for p in ring) < latitude < max(p[1] for p in ring)
        assert min(p[0] for p in ring) < longitude < max(p[0] for p in ring)
        assert event["impact_zone_fallback"]["radius_km"] > 0


def test_small_aftershocks_far_from_the_caller_are_left_out():
    """The feed is searched widely; only zones that reach the caller count."""
    with _feed_answers("kahramanmaras_2023-02-06.geojson"):
        events = _call({**GAZIANTEP, "radius_km": 5})["body"]["events"]

    # The M7.8, M7.5 and M6.7 zones cover Gaziantep. The M5-6 aftershocks
    # 100 km and more to the north do not.
    assert [e["event_id"] for e in events] == ["usgs-us6000jllz", "usgs-us6000jlqa", "usgs-us6000jlm1"]


def test_the_response_survives_json_serialisation():
    """API Gateway serialises the envelope; a datetime in it would be a 500."""
    with _feed_answers("kahramanmaras_2023-02-06.geojson"):
        res = _call(GAZIANTEP)
    assert json.loads(json.dumps(res)) == res


# -------------------------------------------------------------------------
# A location with nothing happening
# -------------------------------------------------------------------------

def test_a_quiet_location_is_a_first_class_negative_answer():
    with _feed_answers("no_events.geojson") as urlopen:
        res = _call({"latitude": 20, "longitude": 10})

    assert res["statusCode"] == 200
    assert res["body"]["disaster_detected"] is False
    assert res["body"]["events"] == []
    assert res["body"]["confidence"] is None
    assert urlopen.call_count == 1, "the negative answer must cost one feed call"


def test_a_negative_answer_names_the_only_event_type_it_covers():
    """Earthquakes are the one feed so far; `false` is not an all-clear for floods."""
    with _feed_answers("no_events.geojson"):
        (source,) = _call({"latitude": 20, "longitude": 10})["body"]["sources_checked"]

    assert source["source"] == "USGS"
    assert source["event_types"] == ["earthquake"]
    assert source["status"] == "ok"


# -------------------------------------------------------------------------
# The feed cannot answer
# -------------------------------------------------------------------------

def test_a_feed_outage_is_an_explicit_error_never_an_all_clear():
    with _feed_is_down():
        res = _call(GAZIANTEP)

    assert res["statusCode"] == 502
    assert res["body"] == {
        "error": "Disaster check failed",
        "code": "DISASTER_CHECK_UNAVAILABLE",
        "retryable": True,
    }
    assert "disaster_detected" not in res["body"]


def test_an_unreadable_feed_answer_is_an_outage_too():
    garbage = mock.patch("urllib.request.urlopen",
                         side_effect=lambda *a, **k: io.BytesIO(b"<html>Bad Gateway</html>"))
    with garbage:
        res = _call(GAZIANTEP)
    assert res["statusCode"] == 502
    assert res["body"]["code"] == "DISASTER_CHECK_UNAVAILABLE"


def test_an_outage_does_not_leak_the_feed_error():
    with mock.patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("proxy 10.0.0.7 refused the connection")):
        res = _call(GAZIANTEP)
    assert "10.0.0.7" not in json.dumps(res["body"])


def test_an_unexpected_failure_is_a_500_without_internals():
    with mock.patch.object(LF, "check_location", side_effect=RuntimeError("boom at line 42")):
        res = _call(GAZIANTEP)
    assert res["statusCode"] == 500
    assert res["body"] == {"error": "Disaster check failed"}


# -------------------------------------------------------------------------
# Requests this slice does not answer
# -------------------------------------------------------------------------

def test_a_news_snippet_is_refused_by_name_without_touching_the_feed():
    """The snippet path is not built; ignoring the snippet would be a guess."""
    with _feed_answers("no_events.geojson") as urlopen:
        res = _call({"news_snippet": "Heavy flooding has submerged parts of Chennai.", **GAZIANTEP})

    assert res["statusCode"] == 501
    assert res["body"]["code"] == "NEWS_SNIPPET_NOT_SUPPORTED"
    assert "disaster_detected" not in res["body"]
    assert not urlopen.called


@pytest.mark.parametrize("payload,fragment", [
    ({}, "latitude and longitude are required"),
    ({"latitude": 37.0}, "latitude and longitude are required"),
    ({"latitude": 91, "longitude": 37.0}, "latitude must be between"),
    ({"latitude": 37.0, "longitude": 37.0, "radius_km": 5000}, "radius_km must be"),
    ({"latitude": 37.0, "longitude": 37.0, "window_hours": 0}, "window_hours must be"),
])
def test_an_unusable_query_is_a_400_that_says_why(payload, fragment):
    with _feed_answers("no_events.geojson") as urlopen:
        res = _call(payload)

    assert res["statusCode"] == 400
    assert fragment in res["body"]["error"]
    assert not urlopen.called


@pytest.mark.parametrize("raw", ["{not json", "", "[1, 2, 3]", '"a bare string"'])
def test_a_body_that_is_not_an_object_is_a_400(raw):
    res = LF.disaster_check_handler({"body": raw}, None)
    assert res["statusCode"] == 400
    assert isinstance(res["body"], dict) and "error" in res["body"]


# -------------------------------------------------------------------------
# How the request arrives
# -------------------------------------------------------------------------

def test_the_router_reaches_the_real_handler():
    """`"service": "disaster_check"` in the body, as the issue specifies."""
    with _feed_answers("kahramanmaras_2023-02-06.geojson"):
        res = LF.lambda_handler(
            {"body": json.dumps({"service": "disaster_check", **GAZIANTEP})}, None
        )
    assert res["statusCode"] == 200
    assert res["body"]["disaster_detected"] is True


def test_a_direct_invoke_where_the_event_is_the_payload():
    """Another Lambda invoking this one sends no `body` wrapper."""
    with _feed_answers("kahramanmaras_2023-02-06.geojson"):
        res = LF.lambda_handler({"service": "disaster_check", **GAZIANTEP}, None)
    assert res["body"]["disaster_detected"] is True
