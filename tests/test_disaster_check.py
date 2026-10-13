"""Which events reach a location, and the zone drawn around each - issue #191.

``check_location`` is feed-neutral: it asks every adapter in ``FEEDS``, keeps
the events whose impact zone reaches the caller's circle, and draws the zone.
The feeds here are fakes, so these tests are about the selection and the
geometry rather than about USGS.

Two properties carry the safety argument of the whole service: a large event
whose epicentre is outside the caller's radius is still found, and a feed that
did not answer can never be reported as a feed that found nothing.
"""
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from services import disaster_check as dc

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


def _event(event_id="quake-1", latitude=0.0, longitude=0.0, radius_km=100.0,
           severity="extreme", confidence="high"):
    started_at = NOW - timedelta(hours=1)
    return {
        "event_id": event_id,
        "event_type": "earthquake",
        "severity": severity,
        "headline": f"M 7.0 - {event_id}",
        "started_at": started_at,
        "expires_at": started_at + timedelta(hours=72),
        "latitude": latitude,
        "longitude": longitude,
        "radius_km": radius_km,
        "volunteer_band_km": 50,
        "confidence": confidence,
        "url": f"https://feed.example/{event_id}",
    }


class _Feed:
    """A stand-in adapter: the four names FEEDS relies on, and a call log."""

    def __init__(self, events=(), raises=None, source="FEED", event_types=("earthquake",)):
        self.SOURCE = source
        self.EVENT_TYPES = event_types
        self.MAX_IMPACT_RADIUS_KM = 1000.0
        self.calls = []
        self._events, self._raises = list(events), raises

    def fetch_events(self, latitude, longitude, search_radius_km, since):
        self.calls.append((latitude, longitude, search_radius_km, since))
        if self._raises:
            raise self._raises
        return self._events


def _check(*feeds, latitude=0.0, longitude=0.0, radius_km=50.0, window_hours=72.0):
    with mock.patch.object(dc, "FEEDS", feeds):
        return dc.check_location(latitude, longitude, radius_km, window_hours, now=NOW)


# -------------------------------------------------------------------------
# Selection
# -------------------------------------------------------------------------

def test_a_location_inside_the_impact_zone_is_detected():
    result = _check(_Feed([_event(latitude=0.3)]))  # about 33 km away
    assert result["disaster_detected"] is True
    assert [e["event_id"] for e in result["events"]] == ["quake-1"]


def test_an_epicentre_beyond_the_callers_radius_still_reaches_them():
    """The false all-clear this service exists to avoid.

    The epicentre is about 111 km away and the caller asked about 50 km, but
    the zone is 100 km wide, so it overlaps the caller's circle.
    """
    result = _check(_Feed([_event(latitude=1.0, radius_km=100.0)]), radius_km=50.0)
    assert result["disaster_detected"] is True


def test_the_feed_is_searched_past_the_callers_radius():
    """Asking the feed only about the caller's circle would hide that event."""
    feed = _Feed()
    _check(feed, latitude=12.5, longitude=77.5, radius_km=50.0, window_hours=24.0)
    assert feed.calls == [(12.5, 77.5, 1050.0, NOW - timedelta(hours=24))]


def test_an_event_whose_zone_stops_short_is_not_detected():
    result = _check(_Feed([_event(latitude=2.0, radius_km=100.0)]), radius_km=50.0)  # ~222 km
    assert result["disaster_detected"] is False
    assert result["events"] == []
    assert result["confidence"] is None


def test_distance_is_measured_across_the_antimeridian():
    """Fiji sits on it: 179.9 and -179.9 are about 22 km apart, not a world."""
    result = _check(_Feed([_event(longitude=-179.9, radius_km=10.0)]), longitude=179.9)
    assert result["disaster_detected"] is True


def test_the_most_severe_event_comes_first():
    events = [
        _event("aftershock", radius_km=10.0, severity="moderate"),
        _event("mainshock", radius_km=250.0, severity="extreme"),
        _event("strong", radius_km=40.0, severity="severe"),
        _event("stronger", radius_km=90.0, severity="severe"),
    ]
    result = _check(_Feed(events))
    assert [e["event_id"] for e in result["events"]] == ["mainshock", "stronger", "strong", "aftershock"]


@pytest.mark.parametrize("confidences,expected", [
    (["high"], "high"), (["medium"], "medium"), (["medium", "high"], "high"),
])
def test_confidence_is_that_of_the_best_attested_event(confidences, expected):
    """One reviewed event is enough to be sure a disaster is there."""
    events = [_event(f"e{i}", confidence=c) for i, c in enumerate(confidences)]
    assert _check(_Feed(events))["confidence"] == expected


# -------------------------------------------------------------------------
# What was actually consulted
# -------------------------------------------------------------------------

def test_a_negative_answer_says_what_it_covers():
    """`false` from an earthquake feed says nothing about floods."""
    result = _check(_Feed(source="USGS", event_types=("earthquake",)))
    assert result["disaster_detected"] is False
    assert result["sources_checked"] == [{
        "source": "USGS",
        "event_types": ["earthquake"],
        "status": "ok",
        "retrieved_at": "2026-10-01T12:00:00Z",
    }]


def test_no_feed_answering_is_an_error_not_an_all_clear():
    with pytest.raises(dc.DisasterCheckUnavailable):
        _check(_Feed(raises=RuntimeError("feed down")))


def test_a_bug_in_an_adapter_also_fails_closed():
    """Any exception from a feed is an unanswered question."""
    with pytest.raises(dc.DisasterCheckUnavailable):
        _check(_Feed(raises=KeyError("properties")))


def test_one_feed_down_is_named_while_the_other_still_answers():
    down = _Feed(raises=RuntimeError("feed down"), source="FLOODS", event_types=("flood",))
    up = _Feed([_event()], source="USGS")
    result = _check(down, up)
    assert result["disaster_detected"] is True
    assert [(s["source"], s["status"]) for s in result["sources_checked"]] == [
        ("FLOODS", "unavailable"), ("USGS", "ok"),
    ]
    assert "retrieved_at" not in result["sources_checked"][0]


# -------------------------------------------------------------------------
# The rendered event
# -------------------------------------------------------------------------

def test_the_rendered_event_carries_its_evidence_and_its_zone():
    (event,) = _check(_Feed([_event(latitude=13.08, longitude=80.25, radius_km=18.04)], source="USGS"),
                      latitude=13.0, longitude=80.2)["events"]
    assert event["started_at"] == "2026-10-01T11:00:00Z"
    assert event["expires_at"] == "2026-10-04T11:00:00Z"
    assert event["boundary_source"] == "modelled"
    assert event["impact_zone_fallback"] == {"center": [13.08, 80.25], "radius_km": 18.0}
    assert event["verified_by"] == [{
        "source": "USGS",
        "url": "https://feed.example/quake-1",
        "retrieved_at": "2026-10-01T12:00:00Z",
    }]
    assert event["llm_cross_check"] is None
    assert event["volunteer_band_km"] == 50
    assert "modelled" in event["advisory"] and "18 km" in event["advisory"]


# -------------------------------------------------------------------------
# Geometry
# -------------------------------------------------------------------------

def test_one_degree_of_latitude_is_about_111_km():
    assert dc.distance_km(0, 0, 1, 0) == pytest.approx(111.195, abs=0.01)


def test_distance_to_the_same_point_is_zero():
    assert dc.distance_km(37.2256, 37.0143, 37.2256, 37.0143) == 0


def _signed_area(ring):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:])) / 2


@pytest.mark.parametrize("latitude,longitude,radius_km", [
    (37.2256, 37.0143, 251.2),   # the recorded mainshock
    (-18.0, 179.5, 300.0),       # across the antimeridian
    (64.0, -150.0, 10.0),        # high latitude, small zone
])
def test_the_zone_is_a_closed_ring_at_the_modelled_radius(latitude, longitude, radius_km):
    polygon = dc.circle_polygon(latitude, longitude, radius_km)
    (ring,) = polygon["coordinates"]

    assert polygon["type"] == "Polygon"
    assert len(ring) == 33 and ring[0] == ring[-1]
    for vertex_longitude, vertex_latitude in ring:
        distance = dc.distance_km(latitude, longitude, vertex_latitude, vertex_longitude)
        assert distance == pytest.approx(radius_km, rel=0.005)
    # RFC 7946: an exterior ring is counterclockwise.
    assert _signed_area(ring) > 0


def test_a_zone_across_the_antimeridian_does_not_jump_to_the_far_side():
    """Wrapping longitudes into +/-180 would draw the ring around the world."""
    (ring,) = dc.circle_polygon(-18.0, 179.5, 300.0)["coordinates"]
    assert max(abs(a[0] - b[0]) for a, b in zip(ring, ring[1:])) < 10
    assert max(longitude for longitude, _ in ring) > 180


# -------------------------------------------------------------------------
# Query validation
# -------------------------------------------------------------------------

def test_defaults_are_applied():
    assert dc.parse_query({"latitude": 37.7749, "longitude": -122.4194}) == {
        "latitude": 37.7749, "longitude": -122.4194, "radius_km": 50.0, "window_hours": 72.0,
    }


def test_numeric_strings_and_zero_coordinates_are_accepted():
    """0, 0 is a real place; a falsy check would reject it as missing."""
    assert dc.parse_query({"latitude": "0", "longitude": 0, "radius_km": "25", "window_hours": 6}) == {
        "latitude": 0.0, "longitude": 0.0, "radius_km": 25.0, "window_hours": 6.0,
    }


@pytest.mark.parametrize("body,message", [
    ({}, "latitude and longitude are required"),
    ({"latitude": 10}, "latitude and longitude are required"),
    ({"latitude": "", "longitude": 10}, "latitude and longitude are required"),
    ({"latitude": "north", "longitude": 10}, "latitude must be a number"),
    ({"latitude": True, "longitude": 10}, "latitude must be a number"),
    ({"latitude": [10], "longitude": 10}, "latitude must be a number"),
    ({"latitude": 90.1, "longitude": 10}, "latitude must be between -90 and 90"),
    ({"latitude": 10, "longitude": -180.5}, "longitude must be between -180 and 180"),
    ({"latitude": "nan", "longitude": 10}, "latitude must be between -90 and 90"),
    ({"latitude": 10, "longitude": "inf"}, "longitude must be between -180 and 180"),
    ({"latitude": 10, "longitude": 10, "radius_km": 0}, "radius_km must be greater than 0 and at most 500"),
    ({"latitude": 10, "longitude": 10, "radius_km": -5}, "radius_km must be greater than 0 and at most 500"),
    ({"latitude": 10, "longitude": 10, "radius_km": 501}, "radius_km must be greater than 0 and at most 500"),
    ({"latitude": 10, "longitude": 10, "window_hours": 169}, "window_hours must be greater than 0 and at most 168"),
    ({"latitude": 10, "longitude": 10, "window_hours": "soon"}, "window_hours must be a number"),
])
def test_an_unusable_query_is_refused_with_a_reason(body, message):
    with pytest.raises(dc.InvalidQuery, match=message):
        dc.parse_query(body)
