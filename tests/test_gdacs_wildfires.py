"""The GDACS wildfire adapter, replayed from recorded responses - issue #191, part 3.

Recorded from the live API on 3 November 2026, each the answer to the exact
request the adapter makes with its clock at noon UTC on 10 January 2025:

    orange_wildfires_2024-12-27.json   every fire that reached Orange or Red
                                       and burned on or after 27 December
                                       2024: 29 fires, the last in August 2026
    burned_area_WF_1023255_13.json     Palisades, Los Angeles: one polygon
                                       with 3 holes
    burned_area_WF_1023277_5.json      Eaton, Los Angeles: two polygons
    burned_area_WF_1029628_32.json     France, July 2026, Red: two polygons,
                                       one with 24 holes

The list was recorded long after every fire in it was out, so the time window
decides each one. It also holds fires that started after the test clock; all
of them are thousands of kilometres from the callers here, so their areas are
never asked for.

GDACS answers "nothing to report" with an empty 204. Everything that cannot be
read raises, because an empty list is an all-clear.
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
from services import gdacs_wildfires as wildfires
from services.geometry import distance_to_area_km

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "gdacs"
LISTING = "orange_wildfires_2024-12-27.json"
PALISADES_AREA = "burned_area_WF_1023255_13.json"
EATON_AREA = "burned_area_WF_1023277_5.json"
FRANCE_AREA = "burned_area_WF_1029628_32.json"
PALISADES, EATON, FRANCE = (1023255, 13), (1023277, 5), (1029628, 32)

# The time the cache sees: noon on 10 January 2025, while both Los Angeles
# fires burned. The default 72-hour window opens on the 7th.
T0 = datetime(2025, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
SINCE = T0 - timedelta(hours=72)
IN_PALISADES = (34.1082, -118.5336)      # 2.6 km inside the burned area
IN_A_HOLE = (34.06177, -118.64881)       # unburned ground inside it, 0.17 km from burned ground
FAR_AWAY = (0.0, -150.0)                 # the Pacific
# The centre GDACS gives the France fire, which lies inside its burned area.
IN_FRANCE = (44.8463, -1.0329)
DURING_THE_FRANCE_FIRE = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


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


def _listing(changes=None, only=None):
    """The recorded list, with properties of some fires changed.

    ``changes`` maps a fire's event ID to the properties to change, or to
    "coordinates" for its centre. ``only`` keeps just those fires.
    """
    listing = _recorded(LISTING)
    if only is not None:
        listing["features"] = [f for f in listing["features"] if f["properties"]["eventid"] in only]
    for feature in listing["features"]:
        overrides = dict((changes or {}).get(feature["properties"]["eventid"], {}))
        coordinates = overrides.pop("coordinates", None)
        if coordinates is not None:
            feature["geometry"]["coordinates"] = coordinates
        feature["properties"].update(overrides)
    return _bytes(listing)


def _palisades(**overrides):
    return _listing({PALISADES[0]: overrides})


def _area_route(event_id):
    return f"{wildfires.GEOMETRY_URL}?eventtype=WF&eventid={event_id}&"


@pytest.fixture
def gdacs_answers(web):
    """GDACS serving a fire list and the recorded burned areas.

    The list is routed by the event type that starts its query, as it is in
    the contract tests, where the flood list shares its URL.
    """
    def _answer(listing=None, area=None):
        listing = (FIXTURES / LISTING).read_bytes() if listing is None else listing
        area = (FIXTURES / PALISADES_AREA).read_bytes() if area is None else area
        return web({
            _area_route(PALISADES[0]): area,
            _area_route(EATON[0]): (FIXTURES / EATON_AREA).read_bytes(),
            _area_route(FRANCE[0]): (FIXTURES / FRANCE_AREA).read_bytes(),
            f"{wildfires.LIST_URL}?eventlist=WF&": listing,
        })
    return _answer


def _answer(near=IN_PALISADES, since=SINCE, radius_km=1.0):
    # Asked about as disaster_check asks: the caller's radius plus the margin.
    return wildfires.fetch_events(near[0], near[1], radius_km + wildfires.MAX_IMPACT_RADIUS_KM, since)


def _fetch(near=IN_PALISADES, since=SINCE):
    return _answer(near, since).events


def _query(request):
    url = urllib.parse.urlsplit(request.full_url)
    return url, urllib.parse.parse_qs(url.query)


def _area_requests(urlopen):
    return [c.args[0].full_url for c in urlopen.call_args_list
            if c.args[0].full_url.startswith(wildfires.GEOMETRY_URL)]


def _list_requests(urlopen):
    return [c for c in urlopen.call_args_list if c.args[0].full_url.startswith(wildfires.LIST_URL)]


# -------------------------------------------------------------------------
# The recording
# -------------------------------------------------------------------------

def test_the_recorded_list_is_every_orange_and_red_fire_since_27_december_2024():
    """Pinned, so a re-recording that changes what the tests stand on fails here first."""
    properties = [feature["properties"] for feature in _recorded(LISTING)["features"]]
    assert len(properties) == 29
    assert {p["eventtype"] for p in properties} == {"WF"}
    assert {p["episodealertlevel"] for p in properties} == {"Orange", "Red"}
    # None was burning when recorded. A fire marked as burning would pass the
    # time filter at every test clock.
    assert {p["iscurrent"] for p in properties} == {"false"}
    assert {PALISADES, EATON, FRANCE} <= {(p["eventid"], p["episodeid"]) for p in properties}


# -------------------------------------------------------------------------
# What is asked for
# -------------------------------------------------------------------------

def test_the_list_query_asks_for_wildfires_that_reached_orange_or_red(gdacs_answers):
    """From seven days before the longest window: on 10 January the window
    can reach back to the 3rd, so the list is asked from 27 December."""
    with gdacs_answers() as urlopen:
        _fetch()

    request = urlopen.call_args_list[0].args[0]
    url, query = _query(request)
    assert (url.scheme, url.netloc) == ("https", "www.gdacs.org")
    assert query == {
        "eventlist": ["WF"],
        "alertlevel": ["Orange;Red"],
        "fromDate": ["2024-12-27"],
        "pageSize": ["100"],
        "pageNumber": ["1"],
        "caller": ["saayam"],
    }
    # The flood list has the same URL. Routing on the event type needs it first.
    assert request.full_url.startswith(f"{wildfires.LIST_URL}?eventlist=WF&")
    assert request.get_header("User-agent") == "saayam-disaster-check"
    assert urlopen.call_args_list[0].kwargs["timeout"] == wildfires.TIMEOUT_SECONDS


def test_only_the_fires_near_the_caller_have_their_burned_area_fetched(gdacs_answers):
    """Of 29 fires, the two in Los Angeles. Each area is asked for by ID, with
    `polygontype=area`: `Affected`, as floods are asked, returns only the centre."""
    with gdacs_answers() as urlopen:
        _fetch()

    assert [_query(c.args[0])[1] for c in urlopen.call_args_list[1:]] == [
        {"eventtype": ["WF"], "eventid": ["1023255"], "episodeid": ["13"], "polygontype": ["area"]},
        {"eventtype": ["WF"], "eventid": ["1023277"], "episodeid": ["5"], "polygontype": ["area"]},
    ]


# -------------------------------------------------------------------------
# What comes back
# -------------------------------------------------------------------------

def test_a_recorded_fire_becomes_a_feed_neutral_event(gdacs_answers):
    with gdacs_answers():
        palisades, eaton = _fetch()

    assert palisades["event_id"] == "gdacs-WF-1023255"
    assert palisades["event_type"] == "wildfire"
    assert palisades["severity"] == "severe"
    assert palisades["headline"] == "Orange wildfire alert: Forest fires in United States"
    assert palisades["started_at"] == datetime(2025, 1, 7, tzinfo=timezone.utc)
    # Last dated 12 January, a whole day: the fire burned until its end.
    assert palisades["expires_at"] == datetime(2025, 1, 13, tzinfo=timezone.utc)
    # GeoJSON is [longitude, latitude]; the event must not have them swapped.
    assert (palisades["latitude"], palisades["longitude"]) == (34.0804, -118.5698)
    assert palisades["area"]["type"] == "MultiPolygon"
    assert palisades["radius_km"] == pytest.approx(10.44, abs=0.01)
    assert palisades["volunteer_band_km"] == 30
    assert palisades["confidence"] == "high"
    assert palisades["url"] == "https://www.gdacs.org/report.aspx?eventid=1023255&episodeid=13&eventtype=WF"
    assert eaton["event_id"] == "gdacs-WF-1023277"


def test_the_centre_gdacs_gives_can_lie_outside_the_burned_area(gdacs_answers):
    """It is 28 m outside here. The centre only decides which areas are
    fetched; the area decides who is in the fire."""
    with gdacs_answers():
        palisades, _ = _fetch()

    assert distance_to_area_km(palisades["latitude"], palisades["longitude"], palisades["area"]) > 0
    assert distance_to_area_km(*IN_PALISADES, palisades["area"]) == 0


def test_holes_in_a_burned_area_are_filled(gdacs_answers):
    """Unburned ground surrounded by fire is in the fire zone."""
    (recorded,) = [f for f in _recorded(PALISADES_AREA)["features"] if f["properties"]["Class"] == "Poly_area"]
    assert len(recorded["geometry"]["coordinates"]) == 4, "an outline and 3 holes, as recorded"

    with gdacs_answers():
        palisades, _ = _fetch()

    ((outline,),) = palisades["area"]["coordinates"]
    assert len(outline) == 131
    assert distance_to_area_km(*IN_A_HOLE, palisades["area"]) == 0


def test_a_burned_area_in_several_parts_keeps_every_part(gdacs_answers):
    with gdacs_answers():
        _, eaton = _fetch()
    assert [len(polygon) for polygon in eaton["area"]["coordinates"]] == [1, 1]


def test_a_red_fire_as_recorded(gdacs_answers, clock):
    """France, July 2026: 47,910 ha in two parts, one with 24 holes."""
    clock.now = DURING_THE_FRANCE_FIRE
    with gdacs_answers(listing=_listing(only={FRANCE[0]})):
        (fire,) = _fetch(near=IN_FRANCE, since=DURING_THE_FRANCE_FIRE - timedelta(hours=72))

    assert fire["severity"] == "extreme"
    assert fire["headline"] == "Red wildfire alert: Forest fires in France"
    assert [len(polygon) for polygon in fire["area"]["coordinates"]] == [1, 1]
    assert fire["radius_km"] == pytest.approx(23.92, abs=0.01)


def test_a_fire_whose_latest_grade_is_green_is_not_reported(gdacs_answers):
    """The fire's own grade is the highest it reached. Its latest update's
    grade is where it stands now."""
    with gdacs_answers(listing=_palisades(episodealertlevel="Green")) as urlopen:
        events = _fetch()
    assert [e["event_id"] for e in events] == ["gdacs-WF-1023277"]
    assert not [u for u in _area_requests(urlopen) if "eventid=1023255&" in u]


@pytest.mark.parametrize("level,severity", [("Orange", "severe"), ("Red", "extreme")])
def test_the_latest_grade_maps_onto_the_shared_severity_scale(gdacs_answers, level, severity):
    with gdacs_answers(listing=_palisades(episodealertlevel=level)):
        palisades, _ = _fetch()
    assert palisades["severity"] == severity
    assert palisades["headline"].startswith(f"{level} wildfire alert")


def test_a_burning_fire_counts_whatever_its_end_date_says(gdacs_answers):
    """While a fire burns, its end date trails real time by one to three days.
    A burning fire is open-ended."""
    with gdacs_answers(listing=_palisades(iscurrent="true", todate="2025-01-06T00:00:00")):
        palisades, _ = _fetch()
    assert palisades["expires_at"] is None


@pytest.mark.parametrize("since,found", [
    (datetime(2025, 1, 12, 23, 59, tzinfo=timezone.utc), True),
    (datetime(2025, 1, 13, 0, 0, tzinfo=timezone.utc), True),
    (datetime(2025, 1, 13, 0, 1, tzinfo=timezone.utc), False),
])
def test_a_fire_burns_until_the_end_of_its_last_day(gdacs_answers, since, found):
    """Both Los Angeles fires were last dated 12 January. A window opening
    late that day still finds them; one opening after it does not, and their
    areas are not fetched."""
    with gdacs_answers() as urlopen:
        events = _fetch(since=since)
    assert bool(events) is found
    assert bool(_area_requests(urlopen)) is found


def test_a_date_written_with_a_zone_ends_when_that_zones_day_ends(gdacs_answers):
    """GDACS writes dates without a zone today. If one comes with a zone, the
    day ends at that zone's midnight: 08:00 UTC for Los Angeles."""
    with gdacs_answers(listing=_palisades(todate="2025-01-12T00:00:00-08:00")):
        palisades, _ = _fetch()
    assert palisades["expires_at"] == datetime(2025, 1, 13, 8, 0, tzinfo=timezone.utc)


def test_a_fire_too_far_away_is_not_fetched(gdacs_answers):
    with gdacs_answers() as urlopen:
        assert _fetch(near=FAR_AWAY) == []
    assert _area_requests(urlopen) == []


def test_positions_are_reduced_to_longitude_and_latitude(gdacs_answers):
    """An altitude is dropped rather than passed through: an unchecked NaN in
    it would make the whole response invalid JSON."""
    def add_altitude(area):
        for ring in _burned(area)["geometry"]["coordinates"]:
            for position in ring:
                position.append(float("nan"))

    with gdacs_answers(area=_palisades_area(add_altitude)):
        palisades, _ = _fetch()
    positions = [p for polygon in palisades["area"]["coordinates"] for ring in polygon for p in ring]
    assert {len(p) for p in positions} == {2}
    json.dumps(palisades["area"], allow_nan=False)


def test_the_evidence_link_is_built_from_the_ids_not_taken_from_the_payload(gdacs_answers):
    with gdacs_answers(listing=_palisades(url={"report": "https://example.com/phish"})):
        palisades, _ = _fetch()
    assert palisades["url"].startswith("https://www.gdacs.org/report.aspx?")


def test_no_content_means_no_fires(gdacs_answers):
    """GDACS answers an empty search with 204 and no body."""
    with gdacs_answers(listing=204) as urlopen:
        assert _fetch() == []
    assert urlopen.call_count == 1


# -------------------------------------------------------------------------
# What cannot be trusted raises
# -------------------------------------------------------------------------

@pytest.mark.parametrize("failure", [
    urllib.error.URLError("no route to host"),
    urllib.error.HTTPError(wildfires.LIST_URL, 503, "Service Unavailable", None, None),
    # GDACS reports its own overload as a 400, with a database pool timeout in the body.
    urllib.error.HTTPError(wildfires.LIST_URL, 400, "Bad Request", None, None),
    TimeoutError("timed out"),
    http.client.IncompleteRead(b'{"features": ['),
])
def test_an_unreachable_list_raises(gdacs_answers, failure):
    with gdacs_answers(listing=failure):
        with pytest.raises(wildfires.FeedError):
            _fetch()


@pytest.mark.parametrize("failure", [
    TimeoutError("timed out"),
    urllib.error.HTTPError(wildfires.GEOMETRY_URL, 404, "Not Found", None, None),
    # What GDACS answered for an update it has no burned area for.
    urllib.error.HTTPError(wildfires.GEOMETRY_URL, 400, "Bad Request", None, None),
])
def test_an_unreachable_burned_area_raises(gdacs_answers, failure):
    with gdacs_answers(area=failure):
        with pytest.raises(wildfires.FeedError):
            _fetch()


def test_a_full_page_is_not_trusted(gdacs_answers):
    """GDACS pages at 100. A full page may have left a fire on the next."""
    listing = _recorded(LISTING)
    listing["features"] = (listing["features"] * 4)[:100]
    with gdacs_answers(listing=_bytes(listing)):
        with pytest.raises(wildfires.FeedError, match="full page"):
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
    b'"no fires"',
    # Iterating either of these yields nothing, which reads as "no fires".
    b'{"features": {}}',
    b'{"features": ""}',
])
def test_an_unreadable_list_raises_rather_than_reporting_nothing(gdacs_answers, payload):
    with gdacs_answers(listing=payload):
        with pytest.raises(wildfires.FeedError):
            _fetch()


@pytest.mark.parametrize("overrides", [
    # Event IDs are numbered per type: a flood here would be read as a fire.
    {"eventtype": "FL"},
    {"eventtype": None},
    {"episodealertlevel": "Unknown"},
    {"episodealertlevel": None},
    {"iscurrent": "yes"},
    {"iscurrent": True},
    {"iscurrent": None},
    {"eventid": "1023255"},
    {"eventid": 0},
    {"eventid": True},
    {"episodeid": None},
    {"fromdate": None},
    {"fromdate": "soon"},
    {"todate": 1736640000},
    {"todate": "9999-12-31T23:00:00-05:00"},
    # The end of the last day is past the last date there is.
    {"todate": "9999-12-31T00:00:00"},
    {"coordinates": [float("nan"), 34.08]},
    {"coordinates": [-118.57, 91.0]},
    {"coordinates": [-118.57]},
])
def test_a_fire_that_cannot_be_trusted_fails_the_whole_answer(gdacs_answers, overrides):
    """A fire is not skipped for being unreadable: it might be the one
    covering the caller."""
    with gdacs_answers(listing=_palisades(**overrides)):
        with pytest.raises(wildfires.FeedError):
            _fetch()


def _palisades_area(change):
    area = _recorded(PALISADES_AREA)
    change(area)
    return _bytes(area)


def _burned(area):
    return next(f for f in area["features"] if f["properties"]["Class"] == "Poly_area")


def _rings(area):
    # Palisades' burned area is one Polygon: its outline, then 3 holes.
    return _burned(area)["geometry"]["coordinates"]


def _other_event(area):
    for feature in area["features"]:
        feature["properties"]["eventid"] = 1


def _other_episode(area):
    for feature in area["features"]:
        feature["properties"]["episodeid"] = 12


def _other_type(area):
    for feature in area["features"]:
        feature["properties"]["eventtype"] = "FL"


def _centroid_only(area):
    area["features"] = [f for f in area["features"] if f["properties"]["Class"] != "Poly_area"]


def _point_area(area):
    _burned(area)["geometry"] = {"type": "Point", "coordinates": [-118.57, 34.08]}


def _short_ring(area):
    _rings(area)[0] = [[-118.5, 34.0], [-118.4, 34.0], [-118.5, 34.0]]


def _short_hole(area):
    _rings(area)[1] = [[-118.5, 34.0], [-118.4, 34.0], [-118.5, 34.0]]


def _nan_position(area):
    _rings(area)[0][0] = [float("nan"), 34.0]


def _nan_in_a_hole(area):
    _rings(area)[1][0] = [float("nan"), 34.0]


def _out_of_range_position(area):
    _rings(area)[0][0] = [-118.5, 95.0]


def _one_number_position(area):
    _rings(area)[0][0] = [-118.5]


def _empty_position(area):
    _rings(area)[0][0] = []


def _no_rings(area):
    _burned(area)["geometry"]["coordinates"] = []


def _hole_first(area):
    rings = _rings(area)
    rings[0], rings[1] = rings[1], rings[0]


@pytest.mark.parametrize("change", [
    _other_event, _other_episode, _other_type, _centroid_only, _point_area, _short_ring, _short_hole,
    _nan_position, _nan_in_a_hole, _out_of_range_position, _one_number_position, _empty_position, _no_rings,
    _hole_first,
])
def test_a_burned_area_that_cannot_be_trusted_fails_the_whole_answer(gdacs_answers, change):
    """Geometry for another event, or a fire with no area, cannot place the
    fire - so neither is passed over quietly. Holes are checked too, though
    they are filled, and a hole listed before the outline would otherwise
    become the whole zone."""
    with gdacs_answers(area=_palisades_area(change)):
        with pytest.raises(wildfires.FeedError):
            _fetch()


@pytest.mark.parametrize("area", [204, b"null", b"[]"])
def test_a_burned_area_answered_with_nothing_usable_fails(gdacs_answers, area):
    with gdacs_answers(area=area):
        with pytest.raises(wildfires.FeedError):
            _fetch()


# -------------------------------------------------------------------------
# The shared answer
# -------------------------------------------------------------------------

def test_the_fire_list_and_areas_are_reused_for_15_minutes(gdacs_answers, clock):
    with gdacs_answers() as urlopen:
        first = _answer()
        clock.now += timedelta(minutes=15)
        second = _answer()
    assert len(_list_requests(urlopen)) == 1
    assert len(_area_requests(urlopen)) == 2
    assert second == first
    assert second.retrieved_at == T0 and not second.stale


def test_after_15_minutes_the_list_is_fetched_again_but_the_areas_are_not(gdacs_answers, clock):
    """A burned area belongs to one update of one fire and never changes."""
    with gdacs_answers() as urlopen:
        _answer()
        clock.now += timedelta(minutes=16)
        answer = _answer()
    assert len(_list_requests(urlopen)) == 2
    assert len(_area_requests(urlopen)) == 2
    assert answer.retrieved_at == T0 + timedelta(minutes=16)


def _episode_14(area):
    for feature in area["features"]:
        feature["properties"]["episodeid"] = 14


def test_a_new_update_of_a_fire_fetches_its_own_burned_area(gdacs_answers, clock):
    with gdacs_answers():
        _answer()
    clock.now += timedelta(minutes=16)
    with gdacs_answers(listing=_palisades(episodeid=14), area=_palisades_area(_episode_14)) as urlopen:
        palisades, _ = _answer().events
    assert [u for u in _area_requests(urlopen) if "eventid=1023255&" in u] == [
        f"{_area_route(1023255)}episodeid=14&polygontype=area",
    ]
    assert palisades["url"].endswith("episodeid=14&eventtype=WF")


def test_a_new_update_without_its_burned_area_is_an_outage_not_the_older_area(gdacs_answers, clock):
    """The older area is smaller: ground burned since would read as clear."""
    with gdacs_answers():
        _answer()
    clock.now += timedelta(minutes=16)
    no_data = urllib.error.HTTPError(wildfires.GEOMETRY_URL, 400, "Bad Request", None, None)
    with gdacs_answers(listing=_palisades(episodeid=14), area=no_data):
        with pytest.raises(wildfires.FeedError):
            _answer()


def test_no_fires_is_reused_too(gdacs_answers, clock):
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
    assert [e["event_id"] for e in answer.events] == ["gdacs-WF-1023255", "gdacs-WF-1023277"]
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
        with pytest.raises(wildfires.FeedError):
            _answer()


def test_a_stale_list_cannot_place_a_fire_whose_burned_area_was_never_fetched(gdacs_answers, clock):
    """The list stands in, but the area of a fire nobody nearby has asked
    about yet cannot be fetched - so there is no answer, not a `false`."""
    with gdacs_answers() as urlopen:
        _answer(near=FAR_AWAY)
    assert _area_requests(urlopen) == []
    clock.now += timedelta(minutes=20)
    with gdacs_answers(listing=urllib.error.URLError("down"), area=TimeoutError("down")):
        with pytest.raises(wildfires.FeedError):
            _answer()


def test_an_unreadable_list_is_not_cached(gdacs_answers, clock):
    with gdacs_answers(listing=b"null"):
        with pytest.raises(wildfires.FeedError):
            _answer()
    clock.now += timedelta(seconds=60)
    with gdacs_answers():
        assert len(_answer().events) == 2


def test_one_list_serves_every_window(gdacs_answers, clock):
    with gdacs_answers() as urlopen:
        _answer(since=T0 - timedelta(hours=168))
        _answer(since=T0 - timedelta(hours=1))
        _answer()
    assert len(_list_requests(urlopen)) == 1


def test_the_last_list_stands_in_across_midnight(gdacs_answers, clock):
    """The list fetched at 23:30 still stands in at 00:05 the next day."""
    clock.now = datetime(2025, 1, 9, 23, 30, tzinfo=timezone.utc)
    with gdacs_answers():
        _answer()
    clock.now = datetime(2025, 1, 10, 0, 5, tzinfo=timezone.utc)
    with gdacs_answers(listing=urllib.error.URLError("down")):
        answer = _answer()
    assert answer.stale is True
    assert [e["event_id"] for e in answer.events] == ["gdacs-WF-1023255", "gdacs-WF-1023277"]


@pytest.mark.parametrize("unreadable", [
    b"null",
    b"<html>Bad Gateway</html>",
    "a fire with a field that cannot be read",
    "a flood listed as a fire",
    "a full page",
])
def test_an_answer_that_came_back_unreadable_never_lets_the_old_list_stand_in(gdacs_answers, clock, unreadable):
    """GDACS answered, so it may be listing a fire the old list does not
    have. Reported as unavailable, not as the old list's "nothing"."""
    with gdacs_answers(listing=204):
        assert _answer().events == []
    clock.now += timedelta(minutes=20)
    if unreadable == "a fire with a field that cannot be read":
        unreadable = _palisades(iscurrent=True)
    elif unreadable == "a flood listed as a fire":
        unreadable = _palisades(eventtype="FL")
    elif unreadable == "a full page":
        listing = _recorded(LISTING)
        listing["features"] = (listing["features"] * 4)[:100]
        unreadable = _bytes(listing)
    with gdacs_answers(listing=unreadable):
        with pytest.raises(wildfires.FeedError):
            _answer()
        clock.now += timedelta(seconds=10)
        with pytest.raises(feed_cache.BackingOff):
            _answer()


def test_a_burned_area_stands_in_for_up_to_7_days(gdacs_answers, clock):
    """An area belongs to one update of one fire and never changes."""
    with gdacs_answers():
        _answer()
    clock.now += timedelta(days=6, hours=23)
    with gdacs_answers(area=TimeoutError("down")):
        palisades, _ = _answer().events
    assert palisades["event_id"] == "gdacs-WF-1023255"
    clock.now += timedelta(hours=2)
    with gdacs_answers(area=TimeoutError("down")):
        with pytest.raises(wildfires.FeedError):
            _answer()


def test_a_window_reaching_back_past_the_shared_list_is_asked_for_on_its_own(gdacs_answers, clock):
    since = T0 - timedelta(hours=200)
    with gdacs_answers() as urlopen:
        _answer(since=since)
    from_dates = [urllib.parse.parse_qs(urllib.parse.urlsplit(c.args[0].full_url).query)["fromDate"][0]
                  for c in _list_requests(urlopen)]
    assert from_dates == ["2024-12-27", "2024-12-26"]


@pytest.mark.parametrize("failure,unreachable", [
    (urllib.error.URLError("no route to host"), True),
    # GDACS reports its own overload as a 400.
    (urllib.error.HTTPError(wildfires.LIST_URL, 400, "Bad Request", None, None), True),
    (TimeoutError("timed out"), True),
    (b"null", False),
    (b"<html>Bad Gateway</html>", False),
])
def test_only_a_gdacs_that_could_not_be_reached_counts_as_unreachable(gdacs_answers, failure, unreachable):
    with gdacs_answers(listing=failure):
        with pytest.raises(wildfires.FeedError) as raised:
            _answer()
    assert isinstance(raised.value, feed_cache.Unreachable) is unreachable
