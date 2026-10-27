"""The USGS earthquake adapter, replayed from recorded responses - issue #191.

``fetch_events`` is the only place disaster_check touches the earthquake feed.
It asks USGS once for every magnitude 5+ earthquake worldwide in the window,
caches that answer, and keeps the events inside the window. These tests replay
answers recorded from the live API, so they cover the real payload shape
without the suite depending on USGS being reachable:

    worldwide_m5_2023-02-06.geojson   6 February 2023, 00:00-12:00 UTC: 15 events,
                                      all in the Kahramanmaras sequence
    worldwide_m5_none.geojson         10 February 2023, 03:00-04:00 UTC: none
    worldwide_m5_2026-10-19.geojson   19-26 October 2026: 73 events worldwide

Each was recorded with an end time so that it can be reproduced; the adapter
itself sends only a start time.

The property that matters most is at the bottom: a feed that cannot be read
raises. It never returns an empty list, because an empty list is an all-clear.
"""
import http.client
import io
import json
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from services import feed_cache
from services import usgs_earthquakes as usgs

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "usgs"
KAHRAMANMARAS = "worldwide_m5_2023-02-06.geojson"
NONE = "worldwide_m5_none.geojson"
LAST_WEEK = "worldwide_m5_2026-10-19.geojson"
SINCE = datetime(2023, 2, 5, 12, 0, 0, tzinfo=timezone.utc)


def _replay(name):
    """Patch the network edge to answer with a recorded response, every time."""
    body = (FIXTURES / name).read_bytes()
    return mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(body))


def _answering(text):
    return mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(text.encode()))


def _feature(**overrides):
    """One USGS feature as JSON text, with a property or the coordinates replaced."""
    coordinates = overrides.pop("coordinates", [10.0, 20.0, 5.0])
    properties = {"mag": 6.1, "time": 1675646254342, "title": "M 6.1 - somewhere",
                  "url": "https://u/x1", "status": "reviewed", **overrides}
    return json.dumps({"id": "x1", "geometry": {"coordinates": coordinates}, "properties": properties})


def _listing(*features):
    return _answering('{"features": [' + ", ".join(features) + "]}")


def _fetch(since=SINCE):
    return usgs.fetch_events(37.2, 37.0, 1050.0, since)


def _query(urlopen, call=-1):
    url = urllib.parse.urlsplit(urlopen.call_args_list[call].args[0].full_url)
    return url, urllib.parse.parse_qs(url.query)


class _Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def clock():
    """Noon on 6 February 2023, for the cache and the shared answer's start."""
    clock = _Clock(datetime(2023, 2, 6, 12, 0, 0, tzinfo=timezone.utc))
    with mock.patch.object(feed_cache, "utcnow", clock):
        yield clock


# -------------------------------------------------------------------------
# What is asked for
# -------------------------------------------------------------------------

def test_the_query_asks_usgs_for_every_earthquake_worldwide_in_the_longest_window():
    """No location is sent, and the answer reaches back seven days, the
    longest window allowed: one answer serves every caller."""
    with _replay(NONE) as urlopen:
        _fetch()

    url, query = _query(urlopen)
    assert urlopen.call_count == 1
    assert (url.scheme, url.netloc) == ("https", "earthquake.usgs.gov")
    assert query == {
        "format": ["geojson"],
        "eventtype": ["earthquake"],
        "minmagnitude": ["5.0"],
        "starttime": ["2023-01-30T12:00:00"],
        "orderby": ["magnitude"],
    }
    request = urlopen.call_args.args[0]
    assert request.get_header("User-agent") == "saayam-disaster-check"
    assert urlopen.call_args.kwargs["timeout"] == usgs.TIMEOUT_SECONDS


def test_the_start_is_rounded_down_to_the_hour_in_utc(clock):
    """USGS reads UTC, whatever zone the clock here is in."""
    clock.now = datetime(2023, 2, 6, 18, 14, 59, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    with _replay(NONE) as urlopen:
        _fetch(since=datetime(2023, 2, 5, 12, 0, 0, tzinfo=timezone.utc))
    _, query = _query(urlopen)
    assert query["starttime"] == ["2023-01-30T12:00:00"]


def test_a_window_reaching_back_past_the_shared_answer_is_asked_for_on_its_own(clock):
    """Not reachable through the service, whose longest window is the one the
    shared answer covers - but never answered from too short an answer."""
    since = clock.now - timedelta(hours=200)
    with _replay(KAHRAMANMARAS) as urlopen:
        answer = _fetch(since=since)
    _, own = _query(urlopen)
    assert urlopen.call_count == 2
    assert own["starttime"] == ["2023-01-29T04:00:00"]
    assert len(answer.events) == 15


# -------------------------------------------------------------------------
# What comes back
# -------------------------------------------------------------------------

def test_a_recorded_earthquake_becomes_a_feed_neutral_event():
    with _replay(KAHRAMANMARAS):
        events = _fetch().events

    assert len(events) == 15
    mainshock = events[0]
    assert mainshock["event_id"] == "usgs-us6000jllz"
    assert mainshock["event_type"] == "earthquake"
    assert mainshock["severity"] == "extreme"
    assert mainshock["headline"].startswith("M 7.8 - Pazarcik earthquake")
    assert mainshock["started_at"] == datetime(2023, 2, 6, 1, 17, 34, 342000, tzinfo=timezone.utc)
    assert mainshock["expires_at"] == datetime(2023, 2, 9, 1, 17, 34, 342000, tzinfo=timezone.utc)
    # GeoJSON is [longitude, latitude]; the event must not have them swapped.
    assert (mainshock["latitude"], mainshock["longitude"]) == (37.2256, 37.0143)
    assert mainshock["radius_km"] == pytest.approx(251.19, abs=0.01)
    assert mainshock["volunteer_band_km"] == 50
    assert mainshock["confidence"] == "high"
    assert mainshock["url"] == "https://earthquake.usgs.gov/earthquakes/eventpage/us6000jllz"


def test_no_events_is_an_empty_answer_not_a_failure(clock):
    with _replay(NONE):
        answer = _fetch()
    assert answer == (
        [], datetime(2023, 2, 6, 12, 0, 0, tzinfo=timezone.utc), False,
    )


def test_events_before_the_window_are_left_out():
    """The query starts at the top of the hour; the window may start later.

    With the window opening at 01:30 the M7.8 (01:17), M5.7 (01:26) and M6.7
    (01:28) are in USGS's answer but before the window.
    """
    since = datetime(2023, 2, 6, 1, 30, 0, tzinfo=timezone.utc)
    with _replay(KAHRAMANMARAS) as urlopen:
        events = _fetch(since=since).events

    assert urlopen.call_count == 1
    ids = {e["event_id"] for e in events}
    assert not ids & {"usgs-us6000jllz", "usgs-us6000jlnn", "usgs-us6000jlm1"}
    assert len(ids) == 12
    assert all(e["started_at"] >= since for e in events)


@pytest.mark.parametrize("status", ["automatic", None, "deleted"])
def test_only_a_reviewed_solution_is_graded_high(status):
    """USGS publishes automatic solutions within minutes and revises them."""
    with _listing(_feature(status=status)):
        (event,) = _fetch().events
    assert event["confidence"] == "medium"


def test_a_review_status_written_in_capitals_still_counts():
    """The Pacific Tsunami Warning Center writes REVIEWED, as recorded on 20 October 2026."""
    with _replay(LAST_WEEK):
        events = _fetch(since=datetime(2026, 10, 19, tzinfo=timezone.utc)).events
    (ptwc,) = [e for e in events if e["event_id"] == "usgs-pt26293000"]
    assert ptwc["confidence"] == "high"


@pytest.mark.parametrize("magnitude,radius_km", [
    (5.0, 10.0), (6.0, 31.6), (7.0, 100.0), (8.0, 316.2), (9.0, 1000.0),
])
def test_impact_radius_follows_the_documented_model(magnitude, radius_km):
    assert usgs.impact_radius_km(magnitude) == pytest.approx(radius_km, abs=0.05)


def test_impact_radius_is_capped():
    """The cap is also the search margin, so no event may exceed it."""
    assert usgs.impact_radius_km(9.5) == usgs.MAX_IMPACT_RADIUS_KM


@pytest.mark.parametrize("magnitude,severity", [
    (5.0, "moderate"), (5.9, "moderate"), (6.0, "severe"), (6.9, "severe"),
    (7.0, "extreme"), (9.1, "extreme"),
])
def test_severity_bands(magnitude, severity):
    assert usgs.severity_for(magnitude) == severity


# -------------------------------------------------------------------------
# The shared answer
# -------------------------------------------------------------------------

def test_a_second_request_within_a_minute_is_answered_from_the_cache(clock):
    with _replay(KAHRAMANMARAS) as urlopen:
        first = _fetch()
        clock.now += timedelta(seconds=60)
        second = _fetch()
    assert urlopen.call_count == 1
    assert second == first
    assert second.retrieved_at == datetime(2023, 2, 6, 12, 0, 0, tzinfo=timezone.utc)


def test_every_window_shares_one_answer_and_keeps_its_own_edge(clock):
    with _replay(KAHRAMANMARAS) as urlopen:
        week = _fetch(since=clock.now - timedelta(hours=168)).events
        wide = _fetch(since=datetime(2023, 2, 6, 1, 0, 0, tzinfo=timezone.utc)).events
        narrow = _fetch(since=datetime(2023, 2, 6, 1, 30, 0, tzinfo=timezone.utc)).events
    assert urlopen.call_count == 1
    assert (len(week), len(wide), len(narrow)) == (15, 15, 12)


def test_the_pause_after_a_failure_covers_every_window(clock):
    """A caller with another window does not wait out the timeout again."""
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")) as urlopen:
        with pytest.raises(usgs.FeedError):
            _fetch(since=clock.now - timedelta(hours=72))
        clock.now += timedelta(seconds=10)
        with pytest.raises(feed_cache.BackingOff):
            _fetch(since=clock.now - timedelta(hours=71))
    assert urlopen.call_count == 1


@pytest.mark.parametrize("failure,unreachable", [
    (urllib.error.URLError("no route to host"), True),
    (urllib.error.HTTPError("https://earthquake.usgs.gov", 503, "Service Unavailable", None, None), True),
    (TimeoutError("timed out"), True),
])
def test_network_failures_count_as_unreachable(failure, unreachable):
    with mock.patch("urllib.request.urlopen", side_effect=failure):
        with pytest.raises(usgs.FeedError) as raised:
            _fetch()
    assert isinstance(raised.value, feed_cache.Unreachable) is unreachable


@pytest.mark.parametrize("payload", ["<html>Bad Gateway</html>", "null", '{"features": [{"id": "x1"}]}'])
def test_an_answer_that_came_back_unreadable_is_not_unreachable(payload):
    with _answering(payload):
        with pytest.raises(usgs.FeedError) as raised:
            _fetch()
    assert not isinstance(raised.value, feed_cache.Unreachable)


def test_after_a_minute_usgs_is_asked_again(clock):
    with _replay(KAHRAMANMARAS) as urlopen:
        _fetch()
        clock.now += timedelta(seconds=61)
        answer = _fetch()
    assert urlopen.call_count == 2
    assert answer.retrieved_at == clock.now


def test_an_old_answer_never_stands_in_for_usgs(clock):
    """An earthquake can happen at any minute, so no earthquake answer is
    ever reused once USGS stops answering."""
    with _replay(KAHRAMANMARAS):
        _fetch()
    clock.now += timedelta(seconds=61)
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
        with pytest.raises(usgs.FeedError):
            _fetch()
        clock.now += timedelta(seconds=30)
        with pytest.raises(feed_cache.BackingOff):
            _fetch()


# -------------------------------------------------------------------------
# What cannot be trusted raises
# -------------------------------------------------------------------------

@pytest.mark.parametrize("failure", [
    urllib.error.URLError("no route to host"),
    urllib.error.HTTPError("https://earthquake.usgs.gov", 503, "Service Unavailable", None, None),
    # USGS refuses a search matching more than 20,000 events with a 400.
    urllib.error.HTTPError("https://earthquake.usgs.gov", 400, "Bad Request", None, None),
    TimeoutError("timed out"),
    ConnectionResetError("reset by peer"),
    http.client.IncompleteRead(b'{"features": ['),
])
def test_an_unreachable_feed_raises_rather_than_reporting_nothing(failure):
    with mock.patch("urllib.request.urlopen", side_effect=failure):
        with pytest.raises(usgs.FeedError):
            _fetch()


@pytest.mark.parametrize("payload", [
    "<html>503 Service Unavailable</html>",
    "",
    "[]",
    "null",
    '{"type": "FeatureCollection"}',
    '{"features": null}',
    # Iterating either of these yields nothing, which reads as "no events".
    '{"features": {}}',
    '{"features": ""}',
    '{"features": [{"id": "x1"}]}',
])
def test_an_unreadable_answer_raises_rather_than_reporting_nothing(payload):
    with _answering(payload):
        with pytest.raises(usgs.FeedError):
            _fetch()


@pytest.mark.parametrize("overrides", [
    {"mag": None},
    {"mag": float("nan")},
    {"mag": float("inf")},
    {"mag": "6.1"},
    {"mag": True},
    {"mag": -1},
    {"mag": 11},
    {"coordinates": [10.0, 137.2, 5.0]},
    {"coordinates": [181.0, 20.0, 5.0]},
    {"coordinates": [float("nan"), 20.0, 5.0]},
    {"coordinates": [10.0, float("inf"), 5.0]},
    {"coordinates": [10.0]},
    {"coordinates": None},
    {"time": None},
    {"time": "yesterday"},
    {"time": -1e15},
    {"time": float("inf")},
])
def test_an_event_that_cannot_be_trusted_fails_the_whole_answer(overrides):
    """A feature that cannot be read is not skipped.

    Skipping it could drop the only event near the caller, and they would be
    told nothing is happening on the strength of a parse error. NaN is the
    quiet version of that: the JSON parser accepts it, and a NaN magnitude or
    coordinate fails every comparison that would keep the event.
    """
    with _listing(_feature(), _feature(**overrides)):
        with pytest.raises(usgs.FeedError):
            _fetch()


def test_an_answer_that_failed_is_not_cached(clock):
    with _answering("<html>Bad Gateway</html>"):
        with pytest.raises(usgs.FeedError):
            _fetch()
    clock.now += timedelta(seconds=60)
    with _replay(KAHRAMANMARAS):
        assert len(_fetch().events) == 15
