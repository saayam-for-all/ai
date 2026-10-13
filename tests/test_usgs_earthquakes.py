"""The USGS earthquake adapter, replayed from recorded responses - issue #191.

``fetch_events`` is the only place disaster_check touches the earthquake feed.
These tests replay two responses recorded from the live API, so they cover the
real payload shape without the suite depending on USGS being reachable:

    kahramanmaras_2023-02-06.geojson   15 events, the M7.8 and M7.5 among them
    no_events.geojson                  the feed asked, and listing nothing

The property that matters most is at the bottom: a feed that cannot be read
raises. It never returns an empty list, because an empty list is an all-clear.
"""
import io
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from services import usgs_earthquakes as usgs

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "usgs"
SINCE = datetime(2023, 2, 5, 12, 0, 0, tzinfo=timezone.utc)


def _replay(name):
    """Patch the network edge to answer with a recorded response."""
    body = (FIXTURES / name).read_bytes()
    return mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(body))


def _answering(text):
    return mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(text.encode()))


def _fetch():
    return usgs.fetch_events(37.2, 37.0, 1050.0, SINCE)


def test_the_query_asks_usgs_for_what_was_requested():
    """The parameters reach the feed, over https, with a caller identified."""
    with _replay("no_events.geojson") as urlopen:
        _fetch()

    request = urlopen.call_args.args[0]
    url = urllib.parse.urlsplit(request.full_url)
    assert (url.scheme, url.netloc) == ("https", "earthquake.usgs.gov")
    assert urllib.parse.parse_qs(url.query) == {
        "format": ["geojson"],
        "eventtype": ["earthquake"],
        "latitude": ["37.2"],
        "longitude": ["37.0"],
        "maxradiuskm": ["1050.0"],
        "minmagnitude": ["5.0"],
        "starttime": ["2023-02-05T12:00:00"],
        "orderby": ["magnitude"],
    }
    assert request.get_header("User-agent") == "saayam-disaster-check"
    assert urlopen.call_args.kwargs["timeout"] == usgs.TIMEOUT_SECONDS


def test_a_recorded_earthquake_becomes_a_feed_neutral_event():
    with _replay("kahramanmaras_2023-02-06.geojson"):
        events = _fetch()

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
    assert mainshock["confidence"] == "high"
    assert mainshock["url"] == "https://earthquake.usgs.gov/earthquakes/eventpage/us6000jllz"


def test_no_events_is_an_empty_list():
    with _replay("no_events.geojson"):
        assert _fetch() == []


def test_an_automatic_solution_is_graded_below_a_reviewed_one():
    """USGS publishes automatic solutions within minutes and revises them."""
    feature = (
        '{"id": "x1", "geometry": {"coordinates": [10.0, 20.0, 5.0]}, "properties": '
        '{"mag": 6.1, "time": 0, "title": "M 6.1 - somewhere", "url": "https://u/x1", '
        '"status": "automatic"}}'
    )
    with _answering('{"features": [' + feature + "]}"):
        (event,) = _fetch()
    assert event["confidence"] == "medium"


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


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("no route to host"),
    urllib.error.HTTPError("https://earthquake.usgs.gov", 503, "Service Unavailable", None, None),
    TimeoutError("timed out"),
    ConnectionResetError("reset by peer"),
])
def test_an_unreachable_feed_raises_rather_than_reporting_nothing(failure):
    with mock.patch("urllib.request.urlopen", side_effect=failure):
        with pytest.raises(usgs.FeedError):
            _fetch()


@pytest.mark.parametrize("payload", [
    "<html>503 Service Unavailable</html>",
    "",
    "[]",
    '{"type": "FeatureCollection"}',
    '{"features": [{"id": "x1"}]}',
    '{"features": [{"id": "x1", "geometry": {"coordinates": [1, 2, 3]}, '
    '"properties": {"mag": null, "time": 0, "title": "t", "url": "u"}}]}',
])
def test_an_unreadable_answer_raises_rather_than_reporting_nothing(payload):
    """A feature that cannot be read is not skipped.

    Skipping it could drop the only event in the response, and the caller
    would be told nothing is happening on the strength of a parse error.
    """
    with _answering(payload):
        with pytest.raises(usgs.FeedError):
            _fetch()
