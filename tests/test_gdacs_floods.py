"""The GDACS flood adapter, replayed from recorded responses - issue #191, part 2.

Recorded from the live API on 20 October 2026, each the answer to the exact
request the adapter makes:

    orange_floods_2026-09-25.json      floods that reached Orange or Red and ran
                                       on or after 25 September: India (to
                                       7 October) and China (to 27 September)
    affected_area_FL_1104121_22.json   India's affected area: 33 polygons, 9 holes
    affected_area_FL_1104081_20.json   China's: one small polygon

The list was recorded after both floods had eased: each reached Orange, but
its latest update is graded Green. Only the latest grade counts, so as
recorded neither is reported. Tests that need a flood to report set India's
latest grade back to Orange, as it was at its peak, and change nothing else.

The properties that matter most are at the bottom. GDACS answers "nothing to
report" with an empty 204. Everything that cannot be read raises, because an
empty list is an all-clear.
"""
import http.client
import json
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from services import feed_cache
from services import gdacs_floods as gdacs

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "gdacs"
LISTING = "orange_floods_2026-09-25.json"
INDIA_AREA = "affected_area_FL_1104121_22.json"
CHINA_AREA = "affected_area_FL_1104081_20.json"

# Inside the window of the India flood, and near it.
SINCE = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
NEAR_INDIA = (11.0, 78.0)
NEAR_CHINA = (31.3, 108.5)
# The time the cache sees: noon on 6 October 2026, while the flood ran.
T0 = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def clock():
    clock = _Clock()
    with mock.patch.object(feed_cache, "utcnow", clock):
        yield clock


def _recorded(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _bytes(document):
    return json.dumps(document).encode()


def _listing(india=None, china=None):
    """The recorded list, with properties of either flood changed."""
    listing = _recorded(LISTING)
    assert [f["properties"]["eventid"] for f in listing["features"]] == [1104121, 1104081]
    for feature, overrides in zip(listing["features"], (india, china)):
        overrides = dict(overrides or {})
        coordinates = overrides.pop("coordinates", None)
        if coordinates is not None:
            feature["geometry"]["coordinates"] = coordinates
        feature["properties"].update(overrides)
    return _bytes(listing)


def _orange_india(**overrides):
    """India as it stood at its peak: latest grade Orange."""
    return _listing(india={"episodealertlevel": "Orange", **overrides})


def _area_route(event_id):
    return f"{gdacs.GEOMETRY_URL}?eventtype=FL&eventid={event_id}&"


@pytest.fixture
def gdacs_answers(web):
    """GDACS serving a list and both recorded affected areas."""
    def _answer(listing=None, area=None):
        listing = _orange_india() if listing is None else listing
        area = (FIXTURES / INDIA_AREA).read_bytes() if area is None else area
        return web({
            _area_route(1104121): area,
            _area_route(1104081): (FIXTURES / CHINA_AREA).read_bytes(),
            gdacs.LIST_URL: listing,
        })
    return _answer


def _answer(near=NEAR_INDIA, since=SINCE):
    return gdacs.fetch_events(near[0], near[1], 1050.0, since)


def _fetch(near=NEAR_INDIA, since=SINCE):
    return _answer(near, since).events


def _query(request):
    url = urllib.parse.urlsplit(request.full_url)
    return url, urllib.parse.parse_qs(url.query)


def _area_requests(urlopen):
    return [c.args[0].full_url for c in urlopen.call_args_list
            if c.args[0].full_url.startswith(gdacs.GEOMETRY_URL)]


# -------------------------------------------------------------------------
# What is asked for
# -------------------------------------------------------------------------

def test_the_list_query_asks_for_floods_that_reached_orange_or_red(gdacs_answers):
    """From ten days before the longest window - seven days, so 6 October
    asks from 19 September - so a flood still running is not dropped for an
    end date that has not caught up with it, and one list serves every
    window."""
    with gdacs_answers() as urlopen:
        _fetch()

    request = urlopen.call_args_list[0].args[0]
    url, query = _query(request)
    assert (url.scheme, url.netloc) == ("https", "www.gdacs.org")
    assert query == {
        "eventlist": ["FL"],
        "alertlevel": ["Orange;Red"],
        "fromDate": ["2026-09-19"],
        "pageSize": ["100"],
        "pageNumber": ["1"],
        "caller": ["saayam"],
    }
    assert request.get_header("User-agent") == "saayam-disaster-check"
    assert urlopen.call_args_list[0].kwargs["timeout"] == gdacs.TIMEOUT_SECONDS


def test_the_area_is_requested_by_id_and_only_the_affected_part(gdacs_answers):
    """The listing carries a geometry URL; it is not followed, and the full
    geometry (1.4 MB for this flood, against 200 KB) is not asked for."""
    with gdacs_answers() as urlopen:
        _fetch()

    (area_request,) = _area_requests(urlopen)
    url, query = _query(urlopen.call_args_list[1].args[0])
    assert area_request == url.geturl()
    assert query == {"eventtype": ["FL"], "eventid": ["1104121"], "episodeid": ["22"], "polygontype": ["Affected"]}


# -------------------------------------------------------------------------
# What comes back
# -------------------------------------------------------------------------

def test_a_recorded_flood_becomes_a_feed_neutral_event(gdacs_answers):
    with gdacs_answers():
        (flood,) = _fetch()

    assert flood["event_id"] == "gdacs-FL-1104121"
    assert flood["event_type"] == "flood"
    assert flood["severity"] == "severe"
    assert flood["headline"] == "Orange flood alert: Flood in India"
    assert flood["started_at"] == datetime(2026, 8, 9, 1, 0, 0, tzinfo=timezone.utc)
    assert flood["expires_at"] == datetime(2026, 10, 7, 1, 0, 0, tzinfo=timezone.utc)
    # GeoJSON is [longitude, latitude]; the event must not have them swapped.
    assert (flood["latitude"], flood["longitude"]) == (11.3324, 78.6099)
    assert flood["area"]["type"] == "MultiPolygon"
    assert len(flood["area"]["coordinates"]) == 33
    assert flood["radius_km"] == pytest.approx(384.2, abs=0.1)
    assert flood["volunteer_band_km"] == 30
    assert flood["confidence"] == "medium"
    assert flood["url"] == "https://www.gdacs.org/report.aspx?eventid=1104121&episodeid=22&eventtype=FL"


def test_a_flood_that_has_eased_to_green_is_not_reported(gdacs_answers):
    """As recorded: both floods once reached Orange, and both are now Green.

    The flood's own grade is the highest it ever reached. Reporting on that
    would keep a flood that was Orange for a day on alert for weeks after.
    """
    with gdacs_answers(listing=(FIXTURES / LISTING).read_bytes()) as urlopen:
        assert _fetch() == []
    assert _area_requests(urlopen) == []


@pytest.mark.parametrize("level,severity", [("Orange", "severe"), ("Red", "extreme")])
def test_the_latest_grade_maps_onto_the_shared_severity_scale(gdacs_answers, level, severity):
    with gdacs_answers(listing=_listing(india={"episodealertlevel": level})):
        (flood,) = _fetch()
    assert flood["severity"] == severity
    assert flood["headline"].startswith(f"{level} flood alert")


def test_a_running_flood_counts_whatever_its_end_date_says(gdacs_answers):
    """GDACS updates a running flood every one to nine days, and its end date
    is the date of the last update until then. A running flood is open-ended."""
    stale = _orange_india(iscurrent="true", todate="2026-09-28T01:00:00")
    with gdacs_answers(listing=stale):
        (flood,) = _fetch()
    assert flood["expires_at"] is None


def test_an_area_published_as_a_single_polygon_is_read_too(gdacs_answers):
    """China's affected area is one Polygon, where India's is a MultiPolygon."""
    listing = _listing(china={"episodealertlevel": "Orange"})
    with gdacs_answers(listing=listing):
        (flood,) = _fetch(near=NEAR_CHINA, since=datetime(2026, 9, 20, tzinfo=timezone.utc))
    assert flood["event_id"] == "gdacs-FL-1104081"
    assert flood["area"]["type"] == "MultiPolygon"
    assert len(flood["area"]["coordinates"]) == 1


def test_positions_are_reduced_to_longitude_and_latitude(gdacs_answers):
    """An altitude is dropped rather than passed through: an unchecked NaN in
    it would make the whole response invalid JSON."""
    def add_altitude(area):
        for ring in _affected(area)["geometry"]["coordinates"][0]:
            for position in ring:
                position.append(float("nan"))

    with gdacs_answers(area=_india_area(add_altitude)):
        (flood,) = _fetch()
    positions = [p for polygon in flood["area"]["coordinates"] for ring in polygon for p in ring]
    assert {len(p) for p in positions} == {2}
    json.dumps(flood["area"], allow_nan=False)


def test_the_evidence_link_is_built_from_the_ids_not_taken_from_the_payload(gdacs_answers):
    with gdacs_answers(listing=_orange_india(url={"report": "https://example.com/phish"})):
        (flood,) = _fetch()
    assert flood["url"].startswith("https://www.gdacs.org/report.aspx?")


def test_no_content_means_no_floods(gdacs_answers):
    """GDACS answers an empty search with 204 and no body."""
    with gdacs_answers(listing=204) as urlopen:
        assert _fetch() == []
    assert urlopen.call_count == 1


def test_a_flood_that_ended_before_the_window_is_skipped(gdacs_answers):
    with gdacs_answers() as urlopen:
        assert _fetch(since=datetime(2026, 10, 8, tzinfo=timezone.utc)) == []
    assert _area_requests(urlopen) == []


def test_a_nearby_flood_that_ended_before_the_window_is_not_fetched(gdacs_answers):
    """China, asked about from near China after it ended on 27 September."""
    listing = _listing(china={"episodealertlevel": "Orange"})
    with gdacs_answers(listing=listing) as urlopen:
        assert _fetch(near=NEAR_CHINA, since=datetime(2026, 9, 28, tzinfo=timezone.utc)) == []
    assert _area_requests(urlopen) == []


def test_a_flood_too_far_away_is_not_fetched(gdacs_answers):
    with gdacs_answers() as urlopen:
        assert _fetch(near=(51.5, -0.12)) == []
    assert _area_requests(urlopen) == []


# -------------------------------------------------------------------------
# What cannot be trusted raises
# -------------------------------------------------------------------------

@pytest.mark.parametrize("failure", [
    urllib.error.URLError("no route to host"),
    urllib.error.HTTPError(gdacs.LIST_URL, 503, "Service Unavailable", None, None),
    # GDACS reports its own overload as a 400, with a database pool timeout in the body.
    urllib.error.HTTPError(gdacs.LIST_URL, 400, "Bad Request", None, None),
    TimeoutError("timed out"),
    http.client.IncompleteRead(b'{"features": ['),
])
def test_an_unreachable_list_raises(gdacs_answers, failure):
    with gdacs_answers(listing=failure):
        with pytest.raises(gdacs.FeedError):
            _fetch()


def test_an_unreachable_area_raises(gdacs_answers):
    with gdacs_answers(area=TimeoutError("timed out")):
        with pytest.raises(gdacs.FeedError):
            _fetch()


def test_a_full_page_is_not_trusted(gdacs_answers):
    """GDACS pages at 100. A full page may have left a flood on the next."""
    listing = json.loads(_orange_india())
    listing["features"] = [listing["features"][0]] + [listing["features"][1]] * 99
    with gdacs_answers(listing=_bytes(listing)):
        with pytest.raises(gdacs.FeedError, match="full page"):
            _fetch()


@pytest.mark.parametrize("payload", [
    b"<html>503 Service Unavailable</html>",
    b"",
    b"[]",
    b'{"type": "FeatureCollection"}',
    b'{"features": null}',
    # A bare null decodes to None, the value that stands for a 204.
    b"null",
    b"\xef\xbb\xbfnull",
    b" null ",
    b"42",
    b'"no floods"',
    # Iterating either of these yields nothing, which reads as "no floods".
    b'{"features": {}}',
    b'{"features": ""}',
])
def test_an_unreadable_list_raises_rather_than_reporting_nothing(gdacs_answers, payload):
    with gdacs_answers(listing=payload):
        with pytest.raises(gdacs.FeedError):
            _fetch()


@pytest.mark.parametrize("overrides", [
    {"episodealertlevel": "Unknown"},
    {"episodealertlevel": None},
    {"iscurrent": "yes"},
    {"iscurrent": True},
    {"iscurrent": None},
    {"eventid": "1104121"},
    {"eventid": 0},
    {"eventid": True},
    {"episodeid": None},
    {"fromdate": None},
    {"fromdate": "soon"},
    {"todate": 1759798800},
    {"todate": "9999-12-31T23:00:00-05:00"},
    {"coordinates": [float("nan"), 11.3]},
    {"coordinates": [78.6, 91.0]},
    {"coordinates": [78.6]},
])
def test_a_flood_that_cannot_be_trusted_fails_the_whole_answer(gdacs_answers, overrides):
    """A flood is not skipped for being unreadable: it might be the one
    covering the caller."""
    with gdacs_answers(listing=_orange_india(**overrides)):
        with pytest.raises(gdacs.FeedError):
            _fetch()


def _india_area(change):
    area = _recorded(INDIA_AREA)
    change(area)
    return _bytes(area)


def _affected(area):
    return next(f for f in area["features"] if f["properties"]["Class"] == "Poly_Affected")


def _other_event(area):
    for feature in area["features"]:
        feature["properties"]["eventid"] = 1


def _centroid_only(area):
    area["features"] = [f for f in area["features"] if f["properties"]["Class"] != "Poly_Affected"]


def _point_area(area):
    _affected(area)["geometry"] = {"type": "Point", "coordinates": [78.6, 11.3]}


def _short_ring(area):
    _affected(area)["geometry"]["coordinates"][0][0] = [[78.0, 11.0], [78.1, 11.0], [78.0, 11.0]]


def _nan_position(area):
    _affected(area)["geometry"]["coordinates"][0][0][0] = [float("nan"), 11.0]


def _out_of_range_position(area):
    _affected(area)["geometry"]["coordinates"][0][0][0] = [78.0, 95.0]


def _one_number_position(area):
    _affected(area)["geometry"]["coordinates"][0][0][0] = [78.0]


def _empty_position(area):
    _affected(area)["geometry"]["coordinates"][0][0][0] = []


def _empty_polygon(area):
    _affected(area)["geometry"]["coordinates"][0] = []


@pytest.mark.parametrize("change", [
    _other_event, _centroid_only, _point_area, _short_ring, _nan_position,
    _out_of_range_position, _one_number_position, _empty_position, _empty_polygon,
])
def test_an_area_that_cannot_be_trusted_fails_the_whole_answer(gdacs_answers, change):
    """GDACS answers a request for an unknown ID with another event's
    geometry, and a flood with no area cannot be placed - so neither is
    passed over quietly."""
    with gdacs_answers(area=_india_area(change)):
        with pytest.raises(gdacs.FeedError):
            _fetch()


@pytest.mark.parametrize("area", [204, b"null", b"[]"])
def test_an_area_answered_with_nothing_usable_fails(gdacs_answers, area):
    with gdacs_answers(area=area):
        with pytest.raises(gdacs.FeedError):
            _fetch()


# -------------------------------------------------------------------------
# The shared answer
# -------------------------------------------------------------------------

def _list_requests(urlopen):
    return [c for c in urlopen.call_args_list if c.args[0].full_url.startswith(gdacs.LIST_URL)]


def test_the_flood_list_and_areas_are_reused_for_15_minutes(gdacs_answers, clock):
    with gdacs_answers() as urlopen:
        first = _answer()
        clock.now += timedelta(minutes=15)
        second = _answer()
    assert len(_list_requests(urlopen)) == 1
    assert len(_area_requests(urlopen)) == 1
    assert second == first
    assert second.retrieved_at == T0 and not second.stale


def test_after_15_minutes_the_list_is_fetched_again_but_the_area_is_not(gdacs_answers, clock):
    """An affected area belongs to one update of one flood and never changes."""
    with gdacs_answers() as urlopen:
        _answer()
        clock.now += timedelta(minutes=16)
        answer = _answer()
    assert len(_list_requests(urlopen)) == 2
    assert len(_area_requests(urlopen)) == 1
    assert answer.retrieved_at == T0 + timedelta(minutes=16)


def test_no_floods_is_reused_too(gdacs_answers, clock):
    with gdacs_answers(listing=204) as urlopen:
        _answer()
        clock.now += timedelta(minutes=10)
        assert _answer().events == []
    assert urlopen.call_count == 1


def test_while_gdacs_is_down_the_last_list_stands_in_marked_stale(gdacs_answers, clock):
    with gdacs_answers():
        _answer()
    clock.now += timedelta(minutes=20)
    with gdacs_answers(listing=urllib.error.URLError("no route to host"), area=TimeoutError("down")):
        answer = _answer()
    (flood,) = answer.events
    assert flood["event_id"] == "gdacs-FL-1104121"
    assert answer.stale is True
    assert answer.retrieved_at == T0


def test_during_the_pause_after_a_failure_gdacs_is_not_asked_again(gdacs_answers, clock):
    with gdacs_answers():
        _answer()
    clock.now += timedelta(minutes=20)
    with gdacs_answers(listing=urllib.error.URLError("no route to host")) as urlopen:
        _answer()
        clock.now += timedelta(seconds=30)
        answer = _answer()
    assert len(_list_requests(urlopen)) == 1
    assert answer.stale is True


def test_a_list_older_than_6_hours_does_not_stand_in(gdacs_answers, clock):
    with gdacs_answers():
        _answer()
    clock.now += timedelta(hours=6, seconds=1)
    with gdacs_answers(listing=urllib.error.URLError("no route to host")):
        with pytest.raises(gdacs.FeedError):
            _answer()


def test_a_stale_list_cannot_place_a_flood_whose_area_was_never_fetched(gdacs_answers, clock):
    """The list stands in, but the area of a flood nobody nearby has asked
    about yet cannot be fetched - so there is no answer, not a `false`."""
    with gdacs_answers() as urlopen:
        _answer(near=(51.5, -0.12))
    assert _area_requests(urlopen) == []
    clock.now += timedelta(minutes=20)
    with gdacs_answers(listing=urllib.error.URLError("down"), area=TimeoutError("down")):
        with pytest.raises(gdacs.FeedError):
            _answer()


def test_an_unreadable_list_is_not_cached(gdacs_answers, clock):
    with gdacs_answers(listing=b"null"):
        with pytest.raises(gdacs.FeedError):
            _answer()
    clock.now += timedelta(seconds=60)
    with gdacs_answers():
        assert len(_answer().events) == 1


def test_one_list_serves_every_window(gdacs_answers, clock):
    with gdacs_answers() as urlopen:
        _answer(since=T0 - timedelta(hours=168))
        _answer(since=T0 - timedelta(hours=1))
        _answer()
    assert len(_list_requests(urlopen)) == 1


def test_the_last_list_stands_in_across_midnight(gdacs_answers, clock):
    """The list fetched at 23:30 still stands in at 00:05 the next day."""
    clock.now = datetime(2026, 10, 5, 23, 30, tzinfo=timezone.utc)
    with gdacs_answers():
        _answer()
    clock.now = datetime(2026, 10, 6, 0, 5, tzinfo=timezone.utc)
    with gdacs_answers(listing=urllib.error.URLError("down")):
        answer = _answer()
    assert answer.stale is True
    assert [e["event_id"] for e in answer.events] == ["gdacs-FL-1104121"]


@pytest.mark.parametrize("unreadable", [
    b"null",
    b"<html>Bad Gateway</html>",
    "a flood with a field that cannot be read",
    "a full page",
])
def test_an_answer_that_came_back_unreadable_never_lets_the_old_list_stand_in(gdacs_answers, clock, unreadable):
    """GDACS answered, so it may be listing a flood the old list does not
    have. Reported as unavailable, not as the old list's "nothing"."""
    with gdacs_answers(listing=_listing()):
        assert _answer().events == []
    clock.now += timedelta(minutes=20)
    if unreadable == "a flood with a field that cannot be read":
        unreadable = _orange_india(iscurrent=True)
    elif unreadable == "a full page":
        listing = json.loads(_orange_india())
        listing["features"] = [listing["features"][0]] + [listing["features"][1]] * 99
        unreadable = _bytes(listing)
    with gdacs_answers(listing=unreadable):
        with pytest.raises(gdacs.FeedError):
            _answer()
        clock.now += timedelta(seconds=10)
        with pytest.raises(feed_cache.BackingOff):
            _answer()


def test_an_affected_area_stands_in_for_up_to_7_days(gdacs_answers, clock):
    """An area belongs to one update of one flood and never changes."""
    with gdacs_answers():
        _answer()
    clock.now += timedelta(days=6, hours=23)
    with gdacs_answers(area=TimeoutError("down")):
        (flood,) = _answer().events
    assert flood["event_id"] == "gdacs-FL-1104121"
    clock.now += timedelta(hours=2)
    with gdacs_answers(area=TimeoutError("down")):
        with pytest.raises(gdacs.FeedError):
            _answer()


def test_a_window_reaching_back_past_the_shared_list_is_asked_for_on_its_own(gdacs_answers, clock):
    since = T0 - timedelta(hours=200)
    with gdacs_answers() as urlopen:
        _answer(since=since)
    from_dates = [urllib.parse.parse_qs(urllib.parse.urlsplit(c.args[0].full_url).query)["fromDate"][0]
                  for c in _list_requests(urlopen)]
    assert from_dates == ["2026-09-19", "2026-09-18"]


@pytest.mark.parametrize("failure,unreachable", [
    (urllib.error.URLError("no route to host"), True),
    # GDACS reports its own overload as a 400.
    (urllib.error.HTTPError(gdacs.LIST_URL, 400, "Bad Request", None, None), True),
    (TimeoutError("timed out"), True),
    (b"null", False),
    (b"<html>Bad Gateway</html>", False),
])
def test_only_a_gdacs_that_could_not_be_reached_counts_as_unreachable(gdacs_answers, failure, unreachable):
    with gdacs_answers(listing=failure):
        with pytest.raises(gdacs.FeedError) as raised:
            _answer()
    assert isinstance(raised.value, feed_cache.Unreachable) is unreachable
