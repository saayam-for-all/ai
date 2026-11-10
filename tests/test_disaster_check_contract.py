"""The disaster_check contract: the Lambda event in, the envelope out - issue #191.

These run the whole coordinate path - router, handler, selection, every feed
adapter - against responses recorded from USGS and GDACS, with only the
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

import lambda_function as LF
from services import feed_cache, gdacs_floods, gdacs_wildfires, usgs_earthquakes

pytestmark = pytest.mark.contract

USGS = Path(__file__).parent / "fixtures" / "usgs"
GDACS = Path(__file__).parent / "fixtures" / "gdacs"

# Recorded worldwide USGS answers. Kahramanmaras: every magnitude 5+
# earthquake on 6 February 2023 from 00:00 to 12:00 UTC, all 15 of them in
# that sequence. None: an hour with none anywhere. Last week: 19-26 October
# 2026, 73 earthquakes worldwide.
KAHRAMANMARAS = "worldwide_m5_2023-02-06.geojson"
NO_EARTHQUAKES = "worldwide_m5_none.geojson"
LAST_WEEK = "worldwide_m5_2026-10-19.geojson"

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

# The Los Angeles fires of January 2025, recorded in tests/fixtures/gdacs
# among every Orange and Red fire since 27 December 2024. GDACS graded both
# Orange. Palisades burned 8,219 ha from 7 to 12 January, and the centre GDACS
# gives it lies just outside its burned area. Eaton burned from 8 to 12
# January, 36 km east of the Palisades point below.
WILDFIRES = "orange_wildfires_2024-12-27.json"
PALISADES_FIRE = (1023255, 13)
EATON_FIRE = (1023277, 5)
IN_THE_PALISADES_FIRE = {"latitude": 34.1082, "longitude": -118.5336}  # 2.6 km inside the burned area
SANTA_MONICA = {"latitude": 34.0195, "longitude": -118.4912}           # 3.9 km outside, 9.9 km from the centre

# Both GDACS feeds ask the same URLs; the event type tells them apart.
FLOOD_AREAS = f"{gdacs_floods.GEOMETRY_URL}?eventtype=FL&"
FIRE_AREAS = f"{gdacs_wildfires.GEOMETRY_URL}?eventtype=WF&"

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

    ``usgs`` names a recorded USGS answer. ``floods`` and ``wildfires`` name a
    recorded GDACS list, or are None for GDACS's empty 204. ``areas`` lists
    the floods, and ``fires`` the wildfires, as (event, episode), whose
    recorded areas GDACS will serve. Pass bytes or an exception in place of a
    name to make a feed misbehave.

    The two GDACS lists share a URL and are routed by the event type that
    starts their query. A request with no route fails, which a feed reports
    as unavailable - so tests that expect an answer check every feed gave one.
    """
    def _answer(usgs=NO_EARTHQUAKES, floods=None, areas=(), wildfires=None, fires=()):
        routes = {
            f"{FLOOD_AREAS}eventid={event_id}&": (GDACS / f"affected_area_FL_{event_id}_{episode_id}.json").read_bytes()
            for event_id, episode_id in areas
        }
        routes.update({
            f"{FIRE_AREAS}eventid={event_id}&": (GDACS / f"burned_area_WF_{event_id}_{episode_id}.json").read_bytes()
            for event_id, episode_id in fires
        })
        routes[f"{gdacs_floods.LIST_URL}?eventlist=FL&"] = _reply(floods, GDACS)
        routes[f"{gdacs_wildfires.LIST_URL}?eventlist=WF&"] = _reply(wildfires, GDACS)
        routes[usgs_earthquakes.QUERY_URL] = _reply(usgs, USGS)
        return web(routes)
    return _answer


class _Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class _ClockThatMoves:
    """The first reading, which is the request's own, then a later one."""

    def __init__(self, first, then):
        self.readings = [first]
        self.then = then

    def __call__(self):
        return self.readings.pop() if self.readings else self.then


def _at(moment):
    """Run requests, and the caches behind them, at a moment."""
    return mock.patch.object(feed_cache, "utcnow", _Clock(moment))


def _on(day):
    """Run the request at noon UTC on a day in October 2026."""
    return _at(datetime(2026, 10, day, 12, 0, 0, tzinfo=timezone.utc))


@pytest.fixture
def on_the_day_of_the_earthquake():
    """Noon UTC on 6 February 2023, inside the recorded USGS answer.

    USGS's answer is filtered to the window here, not by USGS, so a request
    made today would see none of the 2023 earthquakes.
    """
    with _at(datetime(2023, 2, 6, 12, 0, 0, tzinfo=timezone.utc)):
        yield


@pytest.fixture
def during_the_india_flood():
    """Run the request on 6 October 2026, while the recorded flood was running."""
    with _on(6):
        yield


@pytest.fixture
def during_the_los_angeles_fires():
    """Noon UTC on 10 January 2025, while both recorded fires were burning."""
    with _at(datetime(2025, 1, 10, 12, 0, 0, tzinfo=timezone.utc)):
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


def _los_angeles_fires(feeds, **answers):
    return feeds(wildfires=WILDFIRES, fires=[PALISADES_FIRE, EATON_FIRE], **answers)


def _call(payload):
    return LF.disaster_check_handler({"body": json.dumps(payload)}, None)


def _every_feed_answered(body):
    """A missing canned answer makes a feed unavailable, not the test fail."""
    assert [s["status"] for s in body["sources_checked"]] == ["ok", "ok", "ok"]


def _urls(urlopen):
    return [c.args[0].full_url for c in urlopen.call_args_list]


# -------------------------------------------------------------------------
# A location inside a known earthquake
# -------------------------------------------------------------------------

def test_a_location_inside_a_known_earthquake_is_detected(feeds, on_the_day_of_the_earthquake):
    with feeds(usgs=KAHRAMANMARAS):
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


def test_every_event_carries_every_field_of_the_contract(feeds, on_the_day_of_the_earthquake):
    with feeds(usgs=KAHRAMANMARAS):
        events = _call(GAZIANTEP)["body"]["events"]

    assert len(events) > 1
    for event in events:
        assert set(event) == EVENT_FIELDS, event["event_id"]


def test_every_detection_is_backed_by_an_authoritative_source(feeds, on_the_day_of_the_earthquake):
    """No event may reach a caller without the record that confirms it."""
    with feeds(usgs=KAHRAMANMARAS):
        events = _call(GAZIANTEP)["body"]["events"]

    for event in events:
        (evidence,) = event["verified_by"]
        assert evidence["source"] == "USGS"
        assert evidence["url"].startswith("https://earthquake.usgs.gov/earthquakes/eventpage/")
        assert evidence["retrieved_at"].endswith("Z")
        # No model runs on this path, and the response must not imply one did.
        assert event["llm_cross_check"] is None


def test_every_earthquake_zone_says_it_is_modelled(feeds, on_the_day_of_the_earthquake):
    with feeds(usgs=KAHRAMANMARAS):
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


def test_small_aftershocks_far_from_the_caller_are_left_out(feeds, on_the_day_of_the_earthquake):
    """The feed is searched widely; only zones that reach the caller count."""
    with feeds(usgs=KAHRAMANMARAS):
        events = _call({**GAZIANTEP, "radius_km": 5})["body"]["events"]

    # The M7.8, M7.5 and M6.7 zones cover Gaziantep. The M5-6 aftershocks
    # 100 km and more to the north do not.
    assert [e["event_id"] for e in events] == ["usgs-us6000jllz", "usgs-us6000jlqa", "usgs-us6000jlm1"]


def test_the_response_survives_json_serialisation(feeds, on_the_day_of_the_earthquake):
    """API Gateway serialises the envelope; a datetime in it would be a 500."""
    with feeds(usgs=KAHRAMANMARAS):
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
    _every_feed_answered(body)
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
    assert not [u for u in _urls(urlopen) if u.startswith(FLOOD_AREAS)]


def test_a_running_flood_is_reported_with_no_expiry(feeds):
    """While GDACS marks a flood as running, its end date is only the date of
    its last update, which can be days old. The flood stays in, open-ended."""
    with _on(12), _india_flood(feeds, iscurrent="true") as urlopen:
        res = _call(CHENNAI)
    (flood,) = res["body"]["events"]
    assert flood["expires_at"] is None
    assert json.loads(json.dumps(res)) == res
    assert len([u for u in _urls(urlopen) if u.startswith(FLOOD_AREAS)]) == 1


def test_a_flood_that_has_eased_to_green_is_not_reported(feeds, during_the_india_flood):
    """As recorded, the India flood's latest grade is Green. Its own grade,
    Orange, is only the highest it ever reached."""
    with feeds(floods="orange_floods_2026-09-25.json", areas=[INDIA_FLOOD]) as urlopen:
        body = _call(CHENNAI)["body"]
    assert body["disaster_detected"] is False
    assert not [u for u in _urls(urlopen) if u.startswith(FLOOD_AREAS)]


def test_a_flood_response_survives_json_serialisation(feeds, during_the_india_flood):
    with _india_flood(feeds):
        res = _call(CHENNAI)
    # The flood itself, not an error body that would serialise just as well.
    assert [e["event_id"] for e in res["body"]["events"]] == ["gdacs-FL-1104121"]
    assert json.loads(json.dumps(res, allow_nan=False)) == res


# -------------------------------------------------------------------------
# A location inside a known wildfire
# -------------------------------------------------------------------------

def test_a_location_inside_a_known_wildfire_is_detected(feeds, during_the_los_angeles_fires):
    with _los_angeles_fires(feeds):
        res = _call({**IN_THE_PALISADES_FIRE, "radius_km": 1})

    assert res["statusCode"] == 200
    body = res["body"]
    _every_feed_answered(body)
    assert body["disaster_detected"] is True
    # The burned area is observed, and Orange is set with expert review.
    assert body["confidence"] == "high"

    (fire,) = body["events"]
    assert set(fire) == EVENT_FIELDS
    assert fire["event_id"] == "gdacs-WF-1023255"
    assert fire["event_type"] == "wildfire"
    assert fire["severity"] == "severe"
    assert fire["headline"] == "Orange wildfire alert: Forest fires in United States"
    assert fire["started_at"] == "2025-01-07T00:00:00Z"
    # GDACS last dated the fire 12 January, and it burned through that day.
    assert fire["expires_at"] == "2025-01-13T00:00:00Z"
    assert fire["volunteer_band_km"] == 30
    assert fire["llm_cross_check"] is None


def test_at_the_default_radius_both_los_angeles_fires_are_found(feeds, during_the_los_angeles_fires):
    """Eaton's burned area is 36 km from the Palisades point, inside 50 km."""
    with _los_angeles_fires(feeds):
        body = _call(IN_THE_PALISADES_FIRE)["body"]

    _every_feed_answered(body)
    assert [e["event_id"] for e in body["events"]] == ["gdacs-WF-1023255", "gdacs-WF-1023277"]


def test_a_wildfire_zone_is_the_burned_area_gdacs_publishes(feeds, during_the_los_angeles_fires):
    with _los_angeles_fires(feeds):
        (fire,) = _call({**IN_THE_PALISADES_FIRE, "radius_km": 1})["body"]["events"]

    assert fire["boundary_source"] == "authoritative"
    assert fire["impact_zone"]["type"] == "MultiPolygon"
    # One polygon, its outline only: its three holes are unburned ground
    # surrounded by the fire.
    ((outline,),) = fire["impact_zone"]["coordinates"]
    assert len(outline) == 131
    # Centred where GDACS puts the fire, and wide enough to cover all of it.
    assert fire["impact_zone_fallback"] == {"center": [34.0804, -118.5698], "radius_km": 10.5}
    assert "affected area published by GDACS" in fire["advisory"]


def test_every_wildfire_detection_is_backed_by_its_gdacs_report(feeds, during_the_los_angeles_fires):
    with _los_angeles_fires(feeds):
        (fire,) = _call({**IN_THE_PALISADES_FIRE, "radius_km": 1})["body"]["events"]

    (evidence,) = fire["verified_by"]
    assert evidence == {
        "source": "GDACS",
        "url": "https://www.gdacs.org/report.aspx?eventid=1023255&episodeid=13&eventtype=WF",
        "retrieved_at": "2025-01-10T12:00:00Z",
    }


@pytest.mark.parametrize("radius_km,detected", [(5, True), (3, False)])
def test_a_wildfire_counts_when_it_comes_within_the_callers_radius(feeds, during_the_los_angeles_fires, radius_km, detected):
    """Santa Monica is 3.9 km from the edge of the Palisades burned area."""
    with _los_angeles_fires(feeds):
        body = _call({**SANTA_MONICA, "radius_km": radius_km})["body"]

    _every_feed_answered(body)
    assert body["disaster_detected"] is detected


def test_the_burned_area_decides_not_the_circle_around_it(feeds, during_the_los_angeles_fires):
    """Santa Monica is 9.9 km from the centre GDACS gives the fire, inside the
    10.5 km fallback circle, but 3.9 km from any burned ground."""
    with _los_angeles_fires(feeds):
        body = _call({**SANTA_MONICA, "radius_km": 1})["body"]

    _every_feed_answered(body)
    assert body["disaster_detected"] is False


def test_a_wildfire_that_ended_before_the_window_is_not_fetched(feeds):
    """On 20 January the default 72-hour window starts on the 17th. Both fires
    were last dated 12 January, and GDACS no longer marks them as burning."""
    with _at(datetime(2025, 1, 20, 12, 0, 0, tzinfo=timezone.utc)), _los_angeles_fires(feeds) as urlopen:
        body = _call(IN_THE_PALISADES_FIRE)["body"]

    _every_feed_answered(body)
    assert body["disaster_detected"] is False
    assert not [u for u in _urls(urlopen) if u.startswith(FIRE_AREAS)]


def test_a_wildfire_response_survives_json_serialisation(feeds, during_the_los_angeles_fires):
    with _los_angeles_fires(feeds):
        res = _call(IN_THE_PALISADES_FIRE)
    # Both fires, not an error body that would serialise just as well.
    _every_feed_answered(res["body"])
    assert [e["event_id"] for e in res["body"]["events"]] == ["gdacs-WF-1023255", "gdacs-WF-1023277"]
    assert json.loads(json.dumps(res, allow_nan=False)) == res


# -------------------------------------------------------------------------
# Answers shared between requests
# -------------------------------------------------------------------------

def _usgs_requests(urlopen):
    return [u for u in _urls(urlopen) if u.startswith(usgs_earthquakes.QUERY_URL)]


def test_one_worldwide_answer_serves_callers_in_different_places(feeds):
    """Asked about Tibet, then about the Aeolian Islands, USGS is asked once."""
    with _at(datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)), feeds(usgs=LAST_WEEK) as urlopen:
        tibet = _call({"latitude": 32.4, "longitude": 93.8, "window_hours": 168})["body"]
        alicudi = _call({"latitude": 38.54, "longitude": 14.35, "window_hours": 168})["body"]

    assert len(_usgs_requests(urlopen)) == 1
    assert tibet["events"][0]["headline"] == "M 7.0 - 191 km ENE of Nagqu, China"
    assert alicudi["events"][0]["headline"] == "M 5.7 - 61 km WNW of Leni, Italy"
    assert all(e["headline"].endswith("Italy") for e in alicudi["events"])
    assert not any(e["headline"].endswith("China") for e in alicudi["events"])


def test_a_repeated_request_asks_no_feed_at_all(feeds, on_the_day_of_the_earthquake):
    with feeds(usgs=KAHRAMANMARAS) as urlopen:
        first = _call(GAZIANTEP)
        second = _call(GAZIANTEP)
    assert urlopen.call_count == 3, "one call per feed, for the first request only"
    assert second == first


def test_a_cached_answer_reports_when_the_feed_actually_answered(feeds):
    """Raised in the review of part 1: a cached answer must not look current."""
    start = datetime(2023, 2, 6, 12, 0, 0, tzinfo=timezone.utc)
    clock = _Clock(start)
    with mock.patch.object(feed_cache, "utcnow", clock), feeds(usgs=KAHRAMANMARAS):
        _call(GAZIANTEP)
        clock.now = start + timedelta(seconds=45)
        body = _call(GAZIANTEP)["body"]

    assert [(s["source"], s["event_types"], s["retrieved_at"]) for s in body["sources_checked"]] == [
        ("USGS", ["earthquake"], "2023-02-06T12:00:00Z"),
        ("GDACS", ["flood"], "2023-02-06T12:00:00Z"),
        ("GDACS", ["wildfire"], "2023-02-06T12:00:00Z"),
    ]
    assert body["events"][0]["verified_by"][0]["retrieved_at"] == "2023-02-06T12:00:00Z"


def test_while_gdacs_is_down_its_last_answer_stands_in_marked_stale(feeds):
    """GDACS publishes its list about once a day; for up to 6 hours an
    earlier answer stands in, with the time GDACS gave it."""
    start = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
    clock = _Clock(start)
    with mock.patch.object(feed_cache, "utcnow", clock):
        with _india_flood(feeds):
            _call(CHENNAI)
        clock.now = start + timedelta(minutes=20)
        with feeds(floods=DOWN, wildfires=DOWN):
            body = _call(CHENNAI)["body"]

    assert body["disaster_detected"] is True
    (flood,) = body["events"]
    assert flood["verified_by"][0]["retrieved_at"] == "2026-10-06T12:00:00Z"
    assert [(s["source"], s["event_types"], s["status"], s["retrieved_at"]) for s in body["sources_checked"]] == [
        ("USGS", ["earthquake"], "ok", "2026-10-06T12:20:00Z"),
        ("GDACS", ["flood"], "stale", "2026-10-06T12:00:00Z"),
        ("GDACS", ["wildfire"], "stale", "2026-10-06T12:00:00Z"),
    ]


def test_a_quiet_location_while_gdacs_is_down_is_an_error_not_an_all_clear(feeds):
    """Raised in the review of part 6. A list standing in may be missing a
    flood or fire GDACS has raised to Orange since, and a client reading only
    `disaster_detected` would never see that it was stale. With nothing found,
    the answer is a 502 rather than a `false` resting on it."""
    start = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
    clock = _Clock(start)
    with mock.patch.object(feed_cache, "utcnow", clock):
        with _india_flood(feeds):
            assert _call(KOCHI)["body"]["disaster_detected"] is False
        clock.now = start + timedelta(minutes=20)
        with feeds(floods=DOWN, wildfires=DOWN):
            res = _call(KOCHI)

    assert res["statusCode"] == 502
    assert res["body"]["code"] == "DISASTER_CHECK_UNAVAILABLE"
    assert "disaster_detected" not in res["body"]


def test_a_request_made_as_midnight_passed_asks_each_feed_once(feeds):
    """Found while reviewing part 3. The request reads the clock at 23:59:58,
    and the feeds are asked a few seconds later, on the next day. Each shared
    answer still covers the request's whole seven-day window, so none is
    fetched twice."""
    read_at = datetime(2026, 10, 6, 23, 59, 58, tzinfo=timezone.utc)
    clock = _ClockThatMoves(read_at, read_at + timedelta(seconds=5))
    with mock.patch.object(feed_cache, "utcnow", clock), feeds() as urlopen:
        res = _call({"latitude": 20, "longitude": 10, "window_hours": 168})
    assert res["statusCode"] == 200
    assert urlopen.call_count == 3, "one call per feed"


def test_an_earthquake_answer_never_stands_in_once_usgs_is_down(feeds):
    start = datetime(2023, 2, 6, 12, 0, 0, tzinfo=timezone.utc)
    clock = _Clock(start)
    with mock.patch.object(feed_cache, "utcnow", clock):
        with feeds(usgs=KAHRAMANMARAS):
            _call(GAZIANTEP)
        clock.now = start + timedelta(minutes=2)
        with feeds(usgs=DOWN):
            res = _call(GAZIANTEP)
    assert res["statusCode"] == 502


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
    assert urlopen.call_count == 3, "the negative answer must cost one call per feed"


def test_each_gdacs_list_is_asked_for_its_own_event_type(feeds):
    with feeds() as urlopen:
        _call({"latitude": 20, "longitude": 10})

    lists = [u for u in _urls(urlopen) if u.startswith(gdacs_floods.LIST_URL)]
    assert sorted(u.split("&")[0] for u in lists) == [
        f"{gdacs_floods.LIST_URL}?eventlist=FL",
        f"{gdacs_wildfires.LIST_URL}?eventlist=WF",
    ]


def test_a_negative_answer_names_what_it_covers(feeds):
    """`false` covers earthquakes, floods and wildfires, and nothing else."""
    with feeds():
        sources = _call({"latitude": 20, "longitude": 10})["body"]["sources_checked"]

    assert [(s["source"], s["event_types"], s["status"]) for s in sources] == [
        ("USGS", ["earthquake"], "ok"),
        ("GDACS", ["flood"], "ok"),
        ("GDACS", ["wildfire"], "ok"),
    ]


# -------------------------------------------------------------------------
# A feed cannot answer
# -------------------------------------------------------------------------

DOWN = urllib.error.URLError("no route to host")


@pytest.mark.parametrize("down", ["usgs", "floods", "wildfires"])
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


def test_an_earthquake_is_still_reported_while_gdacs_is_down(feeds, on_the_day_of_the_earthquake):
    """A detection stands on its own feed; the dead one is named."""
    with feeds(usgs=KAHRAMANMARAS, floods=DOWN, wildfires=DOWN):
        body = _call(GAZIANTEP)["body"]

    assert body["disaster_detected"] is True
    assert [(s["source"], s["event_types"], s["status"]) for s in body["sources_checked"]] == [
        ("USGS", ["earthquake"], "ok"),
        ("GDACS", ["flood"], "unavailable"),
        ("GDACS", ["wildfire"], "unavailable"),
    ]


def test_a_flood_is_still_reported_while_the_wildfire_feed_is_down(feeds, during_the_india_flood):
    with feeds(floods=_india_listing(), areas=[INDIA_FLOOD], wildfires=DOWN):
        body = _call(CHENNAI)["body"]

    assert [e["event_id"] for e in body["events"]] == ["gdacs-FL-1104121"]
    assert [(s["event_types"], s["status"]) for s in body["sources_checked"]] == [
        (["earthquake"], "ok"), (["flood"], "ok"), (["wildfire"], "unavailable"),
    ]


def test_a_wildfire_is_still_reported_while_the_flood_feed_is_down(feeds, during_the_los_angeles_fires):
    with _los_angeles_fires(feeds, floods=DOWN):
        body = _call({**IN_THE_PALISADES_FIRE, "radius_km": 1})["body"]

    assert [e["event_id"] for e in body["events"]] == ["gdacs-WF-1023255"]
    assert [(s["event_types"], s["status"]) for s in body["sources_checked"]] == [
        (["earthquake"], "ok"), (["flood"], "unavailable"), (["wildfire"], "ok"),
    ]


def test_a_nearby_flood_without_its_area_is_an_outage(feeds, during_the_india_flood):
    """No area, no way to tell who is in the flood - so no `false` either."""
    with feeds(floods=_india_listing(), areas=()) as urlopen:
        res = _call(CHENNAI)
    # The area request found no canned answer, which counts as GDACS failing.
    assert any(u.startswith(FLOOD_AREAS) for u in _urls(urlopen))
    assert res["statusCode"] == 502


def test_a_nearby_wildfire_without_its_burned_area_is_an_outage(web, during_the_los_angeles_fires, capsys):
    """No burned area, no way to tell who is in the fire - so no `false` either.

    GDACS answers the area request with an HTTP error, as it does for a fire
    or update it does not know, rather than the test fixture refusing it.
    """
    no_area = urllib.error.HTTPError(gdacs_wildfires.GEOMETRY_URL, 400, "Bad Request", None, None)
    with web({
        FIRE_AREAS: no_area,
        f"{gdacs_wildfires.LIST_URL}?eventlist=WF&": (GDACS / WILDFIRES).read_bytes(),
        f"{gdacs_floods.LIST_URL}?eventlist=FL&": 204,
        usgs_earthquakes.QUERY_URL: (USGS / NO_EARTHQUAKES).read_bytes(),
    }) as urlopen:
        res = _call(SANTA_MONICA)

    assert any(u.startswith(FIRE_AREAS) for u in _urls(urlopen))
    assert res["statusCode"] == 502
    assert "disaster_check feed GDACS (wildfire) failed: FeedUnreachable" in capsys.readouterr().out


def test_an_unreadable_feed_answer_is_an_outage_too(feeds):
    with feeds(usgs=b"<html>Bad Gateway</html>"):
        res = _call(GAZIANTEP)
    assert res["statusCode"] == 502
    assert res["body"]["code"] == "DISASTER_CHECK_UNAVAILABLE"


def test_an_outage_does_not_leak_the_feed_error(feeds):
    leaky = urllib.error.URLError("proxy 10.0.0.7 refused the connection")
    with feeds(usgs=leaky, floods=leaky, wildfires=leaky):
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

def test_the_router_reaches_the_real_handler(feeds, on_the_day_of_the_earthquake):
    """`"service": "disaster_check"` in the body, as the issue specifies."""
    with feeds(usgs=KAHRAMANMARAS):
        res = LF.lambda_handler(
            {"body": json.dumps({"service": "disaster_check", **GAZIANTEP})}, None
        )
    assert res["statusCode"] == 200
    assert res["body"]["disaster_detected"] is True


def test_a_direct_invoke_where_the_event_is_the_payload(feeds, on_the_day_of_the_earthquake):
    """Another Lambda invoking this one sends no `body` wrapper."""
    with feeds(usgs=KAHRAMANMARAS):
        res = LF.lambda_handler({"service": "disaster_check", **GAZIANTEP}, None)
    assert res["body"]["disaster_detected"] is True
