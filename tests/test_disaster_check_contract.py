"""The disaster_check contract: the Lambda event in, the envelope out - issue #191.

These run the whole coordinate path - router, handler, selection, both feed
adapters - against responses recorded from USGS and GDACS, with only the
network edge replaced. They pin the acceptance criteria covered so far:

    a location inside a known event    -> disaster_detected: true, with the
                                          feed's record in verified_by
    a location with nothing happening  -> disaster_detected: false, from one
                                          call per feed
    a feed unreachable, nothing found  -> DISASTER_CHECK_UNAVAILABLE, and no
                                          disaster_detected field at all

The body stays an object on every path, per #170: the web client reads
``response.body.<field>`` on non-proxy integration.
"""
import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

import lambda_function as LF
from services import disaster_check, gdacs_floods, usgs_earthquakes

pytestmark = pytest.mark.contract

USGS = Path(__file__).parent / "fixtures" / "usgs"
GDACS = Path(__file__).parent / "fixtures" / "gdacs"

# Gaziantep, about 35 km from the M7.8 epicentre of 6 February 2023.
GAZIANTEP = {"latitude": 37.0662, "longitude": 37.3833}

# The flood in India recorded in tests/fixtures/gdacs ran from 9 August to
# 7 October 2026 and reached Orange. Its affected area covers most of Tamil
# Nadu: GDACS puts its centre at 11.33 N, 78.61 E, and the area reaches 384 km
# from there. It was recorded after it had eased, with its latest grade Green,
# so as recorded it is not reported; the tests that need it reported set that
# one grade back to Orange, as at its peak.
INDIA_FLOOD = (1104121, 22)
CHENNAI = {"latitude": 13.0827, "longitude": 80.2707}       # inside, 265 km from the centre
BENGALURU = {"latitude": 12.9716, "longitude": 77.5946}     # 26 km outside the area
KOCHI = {"latitude": 9.9312, "longitude": 76.2673}          # 74 km outside, well inside 384 km
DRY_GROUND = {"latitude": 11.8046, "longitude": 79.6823}    # in a hole, 0.47 km from the water

EVENT_FIELDS = {
    "event_id", "event_type", "severity", "headline", "started_at", "expires_at",
    "impact_zone", "impact_zone_fallback", "boundary_source", "verified_by",
    "llm_cross_check", "volunteer_band_km", "advisory",
}


def _reply(value, folder):
    if value is None:
        return 204
    if isinstance(value, (bytes, BaseException)):
        return value
    return (folder / value).read_bytes()


@pytest.fixture
def feeds(web):
    """Answer each feed from a recorded response.

    ``usgs`` names a recorded USGS answer. ``floods`` names a recorded GDACS
    flood list, or is None for GDACS's empty 204. ``areas`` lists the floods,
    as (event, episode), whose recorded affected areas GDACS will serve. Pass
    bytes or an exception in place of a name to make a feed misbehave.
    """
    def _answer(usgs="no_events.geojson", floods=None, areas=()):
        routes = {
            f"{gdacs_floods.GEOMETRY_URL}?eventtype=FL&eventid={event_id}&":
                (GDACS / f"affected_area_FL_{event_id}_{episode_id}.json").read_bytes()
            for event_id, episode_id in areas
        }
        routes[gdacs_floods.LIST_URL] = _reply(floods, GDACS)
        routes[usgs_earthquakes.QUERY_URL] = _reply(usgs, USGS)
        return web(routes)
    return _answer


def _on(day):
    """Run the request at noon UTC on a day in October 2026."""
    moment = datetime(2026, 10, day, 12, 0, 0, tzinfo=timezone.utc)
    return mock.patch.object(disaster_check, "_utcnow", return_value=moment)


@pytest.fixture
def during_the_india_flood():
    """Run the request on 6 October 2026, while the recorded flood was running."""
    with _on(6):
        yield


def _india_listing(**changes):
    """The recorded flood list, with India's latest grade back at Orange."""
    listing = json.loads((GDACS / "orange_floods_2026-09-25.json").read_text(encoding="utf-8"))
    india = listing["features"][0]["properties"]
    assert india["eventid"] == INDIA_FLOOD[0]
    india.update({"episodealertlevel": "Orange", **changes})
    return json.dumps(listing).encode()


def _india_flood(feeds, **changes):
    return feeds(floods=_india_listing(**changes), areas=[INDIA_FLOOD])


def _call(payload):
    return LF.disaster_check_handler({"body": json.dumps(payload)}, None)


def _urls(urlopen):
    return [c.args[0].full_url for c in urlopen.call_args_list]


# -------------------------------------------------------------------------
# A location inside a known earthquake
# -------------------------------------------------------------------------

def test_a_location_inside_a_known_earthquake_is_detected(feeds):
    with feeds(usgs="kahramanmaras_2023-02-06.geojson"):
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


def test_every_event_carries_every_field_of_the_contract(feeds):
    with feeds(usgs="kahramanmaras_2023-02-06.geojson"):
        events = _call(GAZIANTEP)["body"]["events"]

    assert len(events) > 1
    for event in events:
        assert set(event) == EVENT_FIELDS, event["event_id"]


def test_every_detection_is_backed_by_an_authoritative_source(feeds):
    """No event may reach a caller without the record that confirms it."""
    with feeds(usgs="kahramanmaras_2023-02-06.geojson"):
        events = _call(GAZIANTEP)["body"]["events"]

    for event in events:
        (evidence,) = event["verified_by"]
        assert evidence["source"] == "USGS"
        assert evidence["url"].startswith("https://earthquake.usgs.gov/earthquakes/eventpage/")
        assert evidence["retrieved_at"].endswith("Z")
        # No model runs on this path, and the response must not imply one did.
        assert event["llm_cross_check"] is None


def test_every_earthquake_zone_says_it_is_modelled(feeds):
    with feeds(usgs="kahramanmaras_2023-02-06.geojson"):
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


def test_small_aftershocks_far_from_the_caller_are_left_out(feeds):
    """The feed is searched widely; only zones that reach the caller count."""
    with feeds(usgs="kahramanmaras_2023-02-06.geojson"):
        events = _call({**GAZIANTEP, "radius_km": 5})["body"]["events"]

    # The M7.8, M7.5 and M6.7 zones cover Gaziantep. The M5-6 aftershocks
    # 100 km and more to the north do not.
    assert [e["event_id"] for e in events] == ["usgs-us6000jllz", "usgs-us6000jlqa", "usgs-us6000jlm1"]


def test_the_response_survives_json_serialisation(feeds):
    """API Gateway serialises the envelope; a datetime in it would be a 500."""
    with feeds(usgs="kahramanmaras_2023-02-06.geojson"):
        res = _call(GAZIANTEP)
    assert json.loads(json.dumps(res)) == res


# -------------------------------------------------------------------------
# A location inside a known flood
# -------------------------------------------------------------------------

def test_a_location_inside_a_known_flood_is_detected(feeds, during_the_india_flood):
    """Chennai is 265 km from the centre GDACS gives, and inside the flood."""
    with _india_flood(feeds):
        res = _call(CHENNAI)

    assert res["statusCode"] == 200
    body = res["body"]
    assert body["disaster_detected"] is True
    # GDACS flood alerts are forecasts, so they are never graded high.
    assert body["confidence"] == "medium"

    (flood,) = body["events"]
    assert set(flood) == EVENT_FIELDS
    assert flood["event_id"] == "gdacs-FL-1104121"
    assert flood["event_type"] == "flood"
    assert flood["severity"] == "severe"
    assert flood["headline"] == "Orange flood alert: Flood in India"
    assert flood["started_at"] == "2026-08-09T01:00:00Z"
    assert flood["expires_at"] == "2026-10-07T01:00:00Z"
    assert flood["volunteer_band_km"] == 30
    assert flood["llm_cross_check"] is None


def test_a_flood_zone_is_the_area_gdacs_publishes(feeds, during_the_india_flood):
    with _india_flood(feeds):
        (flood,) = _call(CHENNAI)["body"]["events"]

    assert flood["boundary_source"] == "authoritative"
    assert flood["impact_zone"]["type"] == "MultiPolygon"
    assert len(flood["impact_zone"]["coordinates"]) == 33
    # The fallback circle is centred where GDACS puts the flood and is wide
    # enough to cover the whole affected area.
    assert flood["impact_zone_fallback"] == {"center": [11.3324, 78.6099], "radius_km": 384.2}
    assert "affected area published by GDACS" in flood["advisory"]


def test_every_flood_detection_is_backed_by_its_gdacs_report(feeds, during_the_india_flood):
    with _india_flood(feeds):
        (flood,) = _call(CHENNAI)["body"]["events"]

    (evidence,) = flood["verified_by"]
    assert evidence == {
        "source": "GDACS",
        "url": "https://www.gdacs.org/report.aspx?eventid=1104121&episodeid=22&eventtype=FL",
        "retrieved_at": "2026-10-06T12:00:00Z",
    }


@pytest.mark.parametrize("radius_km,detected", [(50, True), (10, False)])
def test_a_flood_counts_when_it_comes_within_the_callers_radius(feeds, during_the_india_flood, radius_km, detected):
    """Bengaluru is 26 km from the edge of the affected area."""
    with _india_flood(feeds):
        body = _call({**BENGALURU, "radius_km": radius_km})["body"]
    assert body["disaster_detected"] is detected


def test_the_published_area_decides_not_the_circle_around_it(feeds, during_the_india_flood):
    """Kochi is 300 km from the centre, well inside the 384 km fallback
    circle, but 74 km from any water. It is not in this flood."""
    with _india_flood(feeds):
        body = _call({**KOCHI, "radius_km": 50})["body"]
    assert body["disaster_detected"] is False


@pytest.mark.parametrize("radius_km,detected", [(0.1, False), (1, True)])
def test_dry_ground_inside_a_flood_is_not_in_it(feeds, during_the_india_flood, radius_km, detected):
    """A hole in the affected area is outside it, until the radius reaches the water."""
    with _india_flood(feeds):
        body = _call({**DRY_GROUND, "radius_km": radius_km})["body"]
    assert body["disaster_detected"] is detected


def test_a_flood_that_ended_before_the_window_is_not_fetched(feeds):
    """On 12 October the default 72-hour window starts on the 9th; the flood
    ended on the 7th and GDACS no longer marks it as running."""
    with _on(12), _india_flood(feeds) as urlopen:
        body = _call(CHENNAI)["body"]
    assert body["disaster_detected"] is False
    assert not [u for u in _urls(urlopen) if u.startswith(gdacs_floods.GEOMETRY_URL)]


def test_a_running_flood_is_reported_with_no_expiry(feeds):
    """While GDACS marks a flood as running, its end date is only the date of
    its last update, which can be days old. The flood stays in, open-ended."""
    with _on(12), _india_flood(feeds, iscurrent="true") as urlopen:
        res = _call(CHENNAI)
    (flood,) = res["body"]["events"]
    assert flood["expires_at"] is None
    assert json.loads(json.dumps(res)) == res
    assert len([u for u in _urls(urlopen) if u.startswith(gdacs_floods.GEOMETRY_URL)]) == 1


def test_a_flood_that_has_eased_to_green_is_not_reported(feeds, during_the_india_flood):
    """As recorded, the India flood's latest grade is Green. Its own grade,
    Orange, is only the highest it ever reached."""
    with feeds(floods="orange_floods_2026-09-25.json", areas=[INDIA_FLOOD]) as urlopen:
        body = _call(CHENNAI)["body"]
    assert body["disaster_detected"] is False
    assert not [u for u in _urls(urlopen) if u.startswith(gdacs_floods.GEOMETRY_URL)]


def test_a_flood_response_survives_json_serialisation(feeds, during_the_india_flood):
    with _india_flood(feeds):
        res = _call(CHENNAI)
    assert json.loads(json.dumps(res)) == res


# -------------------------------------------------------------------------
# A location with nothing happening
# -------------------------------------------------------------------------

def test_a_quiet_location_is_a_first_class_negative_answer(feeds):
    with feeds() as urlopen:
        res = _call({"latitude": 20, "longitude": 10})

    assert res["statusCode"] == 200
    assert res["body"]["disaster_detected"] is False
    assert res["body"]["events"] == []
    assert res["body"]["confidence"] is None
    assert urlopen.call_count == 2, "the negative answer must cost one call per feed"


def test_a_negative_answer_names_what_it_covers(feeds):
    """`false` covers earthquakes and floods, and nothing else."""
    with feeds():
        sources = _call({"latitude": 20, "longitude": 10})["body"]["sources_checked"]

    assert [(s["source"], s["event_types"], s["status"]) for s in sources] == [
        ("USGS", ["earthquake"], "ok"),
        ("GDACS", ["flood"], "ok"),
    ]


# -------------------------------------------------------------------------
# A feed cannot answer
# -------------------------------------------------------------------------

DOWN = urllib.error.URLError("no route to host")


@pytest.mark.parametrize("down", ["usgs", "floods"])
def test_any_feed_outage_with_nothing_found_is_an_error_not_an_all_clear(feeds, down):
    with feeds(**{down: DOWN}):
        res = _call(GAZIANTEP)

    assert res["statusCode"] == 502
    assert res["body"] == {
        "error": "Disaster check failed",
        "code": "DISASTER_CHECK_UNAVAILABLE",
        "retryable": True,
    }
    assert "disaster_detected" not in res["body"]


def test_an_earthquake_is_still_reported_while_gdacs_is_down(feeds):
    """A detection stands on its own feed; the dead one is named."""
    with feeds(usgs="kahramanmaras_2023-02-06.geojson", floods=DOWN):
        body = _call(GAZIANTEP)["body"]

    assert body["disaster_detected"] is True
    assert [(s["source"], s["status"]) for s in body["sources_checked"]] == [
        ("USGS", "ok"), ("GDACS", "unavailable"),
    ]


def test_a_nearby_flood_without_its_area_is_an_outage(feeds, during_the_india_flood):
    """No area, no way to tell who is in the flood - so no `false` either."""
    with feeds(floods=_india_listing(), areas=()) as urlopen:
        res = _call(CHENNAI)
    # The area request found no canned answer, which counts as GDACS failing.
    assert any(u.startswith(gdacs_floods.GEOMETRY_URL) for u in _urls(urlopen))
    assert res["statusCode"] == 502


def test_an_unreadable_feed_answer_is_an_outage_too(feeds):
    with feeds(usgs=b"<html>Bad Gateway</html>"):
        res = _call(GAZIANTEP)
    assert res["statusCode"] == 502
    assert res["body"]["code"] == "DISASTER_CHECK_UNAVAILABLE"


def test_an_outage_does_not_leak_the_feed_error(feeds):
    leaky = urllib.error.URLError("proxy 10.0.0.7 refused the connection")
    with feeds(usgs=leaky, floods=leaky):
        res = _call(GAZIANTEP)
    assert "10.0.0.7" not in json.dumps(res["body"])


@pytest.mark.parametrize("broken", ["check_location", "parse_query"])
def test_an_unexpected_failure_is_a_500_without_internals(broken):
    """Nothing escapes the handler: a direct invoke has no router to catch it."""
    with mock.patch.object(LF, broken, side_effect=RuntimeError("boom at line 42")):
        res = _call(GAZIANTEP)
    assert res["statusCode"] == 500
    assert res["body"] == {"error": "Disaster check failed"}


# -------------------------------------------------------------------------
# Requests this slice does not answer
# -------------------------------------------------------------------------

def test_a_news_snippet_is_refused_by_name_without_touching_the_feeds(feeds):
    """The snippet path is not built; ignoring the snippet would be a guess."""
    with feeds() as urlopen:
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
    ({"latitude": 10 ** 400, "longitude": 37.0}, "latitude must be between"),
])
def test_an_unusable_query_is_a_400_that_says_why(feeds, payload, fragment):
    with feeds() as urlopen:
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

def test_the_router_reaches_the_real_handler(feeds):
    """`"service": "disaster_check"` in the body, as the issue specifies."""
    with feeds(usgs="kahramanmaras_2023-02-06.geojson"):
        res = LF.lambda_handler(
            {"body": json.dumps({"service": "disaster_check", **GAZIANTEP})}, None
        )
    assert res["statusCode"] == 200
    assert res["body"]["disaster_detected"] is True


def test_a_direct_invoke_where_the_event_is_the_payload(feeds):
    """Another Lambda invoking this one sends no `body` wrapper."""
    with feeds(usgs="kahramanmaras_2023-02-06.geojson"):
        res = LF.lambda_handler({"service": "disaster_check", **GAZIANTEP}, None)
    assert res["body"]["disaster_detected"] is True
