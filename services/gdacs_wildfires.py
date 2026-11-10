"""GDACS wildfire feed adapter for disaster_check - issue #191, part 3.

GDACS, the Global Disaster Alert and Coordination System, is run by the UN
(OCHA) and the European Commission's Joint Research Centre. It takes its
wildfires from GWIS, the JRC's Global Wildfire Information System, which maps
the area each fire has burned from MODIS and VIIRS satellite detections every
day. The API is public and takes no key.

Each fire's zone is the burned area GDACS publishes for it, reported as
``boundary_source: "authoritative"``. The centre GDACS gives a fire can lie
outside that area, so the centre only decides which areas are fetched.

Exposes the same four names as services/usgs_earthquakes.py. The fire list is
the same for every caller worldwide, so it is cached and shared, and each
burned area is cached by fire and update.

This is a copy of services/gdacs_floods.py with the wildfire differences, so
that the flood adapter, still under review, is left as it is. The GDACS code
the two have in common can move to one shared module once both are merged.
"""
import http.client
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from services import feed_cache
from services.geometry import distance_km, farthest_km

SOURCE = "GDACS"
EVENT_TYPES = ("wildfire",)
# GDACS's own code for a wildfire. Event IDs are numbered per type, so a
# flood and a fire can share one.
EVENT_TYPE = "WF"

LIST_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GEOMETRY_URL = "https://www.gdacs.org/gdacsapi/api/polygons/getgeometry"
REPORT_URL = "https://www.gdacs.org/report.aspx"
TIMEOUT_SECONDS = 8
# The most fires GDACS returns in one page of results.
PAGE_SIZE = 100

# GDACS grades a fire Green automatically once it has burned 5,000 ha, "even
# in absence of impacts", Orange when it directly affects people or built-up
# areas, and Red when the impact is severe. Only Orange and Red are reported.
# They are rare, 14 to 15 a year, but Green lists run to many pages, and the
# same query paged at different sizes left out different fires: a list that
# may be missing a fire cannot back an all-clear. A first-pass value awaiting
# review - see the README.
ALERT_LEVELS = ("Orange", "Red")
SEVERITY = {"Green": "minor", "Orange": "severe", "Red": "extreme"}

# While a fire is running, its end date trails real time by one to three
# days. The list is asked for from this much earlier than the window, so a
# fire still burning is not dropped for an end date that has not caught up.
LOOKBACK_DAYS = 7

# Only fires whose centre is within this distance of the caller's circle have
# their burned area fetched. Across five Orange and Red fires measured in
# November 2026, the farthest any burned area reached from its centre was
# 40 km.
MAX_IMPACT_RADIUS_KM = 500.0

# The same as for floods. Awaiting review.
VOLUNTEER_BAND_KM = 30

# Kept as long as the flood list and areas, for the same reasons: GDACS can be
# unreachable for hours, and a burned area belongs to one update of one fire
# and never changes. GDACS updates a burning fire one to three times a day,
# so a list standing in can be an update or two behind. First-pass values
# awaiting review.
LIST_FRESH_SECONDS = 15 * 60
LIST_STALE_SECONDS = 6 * 60 * 60
AREA_FRESH_SECONDS = 24 * 60 * 60
AREA_STALE_SECONDS = 7 * 24 * 60 * 60

# The shared list reaches back far enough for the longest window
# disaster_check accepts, and an hour more, for the seconds between a request
# reading the clock and this list being fetched, after USGS and the flood
# list: without it, a request made as midnight passed would fetch the list a
# second time. A window reaching further back is asked for on its own.
COVER_HOURS = 169

_LISTS = feed_cache.FeedCache(fresh_seconds=LIST_FRESH_SECONDS, stale_seconds=LIST_STALE_SECONDS, max_entries=1)
# Burned areas are small: 5 to 90 KB as JSON for the fires measured.
_AREAS = feed_cache.FeedCache(fresh_seconds=AREA_FRESH_SECONDS, stale_seconds=AREA_STALE_SECONDS, max_entries=8)


class FeedError(Exception):
    """The feed could not be reached, or answered with something unusable."""


class FeedUnreachable(FeedError, feed_cache.Unreachable):
    """GDACS could not be reached: a network error, a timeout or an HTTP error."""


def fetch_events(latitude, longitude, search_radius_km, since):
    """Orange and Red wildfires burning at any time since a moment, near a point.

    Raises FeedError when GDACS is unreachable or its answer cannot be read,
    including when a nearby fire's burned area cannot be fetched, or
    feed_cache.BackingOff in the minute after a failure with nothing cached
    to stand in. No fires is therefore a real answer: GDACS was asked and
    listed nothing.
    """
    listing = _LISTS.get("wildfires", _shared)
    from_date, fires = listing.value
    retrieved_at, stale = listing.fetched_at, listing.stale
    needed = _from_date(since)
    if needed < from_date:
        fires, retrieved_at, stale = _fires(needed), feed_cache.utcnow(), False

    events = []
    for fire in fires:
        if fire["alert_level"] not in ALERT_LEVELS:
            continue
        if not fire["running"] and fire["ended_at"] < since:
            continue
        if distance_km(latitude, longitude, fire["latitude"], fire["longitude"]) > search_radius_km:
            continue
        try:
            # Each update of a fire has its own, larger, burned area. An
            # earlier update's area is never used for a later one: it could
            # leave out ground that has burned since.
            area = _AREAS.get((fire["event_id"], fire["episode_id"]), lambda: _burned_area(fire))
        except (KeyError, TypeError, ValueError, OverflowError) as e:
            raise FeedError(f"GDACS burned area was not in the expected shape: {type(e).__name__}: {e}") from e
        events.append(_event(fire, area.value))
    return feed_cache.FeedAnswer(events, retrieved_at, stale)


def _shared():
    from_date = _from_date(feed_cache.utcnow() - timedelta(hours=COVER_HOURS))
    return from_date, _fires(from_date)


def _from_date(since):
    """The date GDACS is asked from for a window starting at ``since``.

    GDACS returns the fires whose end date is on or after it. Dates written
    this way sort as text.
    """
    return (since - timedelta(days=LOOKBACK_DAYS)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def _fires(from_date):
    """Every fire GDACS lists from a date, read and checked, or FeedError."""
    # The event type comes first in the query, where the tests route on it.
    listing = _get(LIST_URL, {
        "eventlist": EVENT_TYPE,
        "alertlevel": ";".join(ALERT_LEVELS),
        "fromDate": from_date,
        "pageSize": PAGE_SIZE,
        "pageNumber": 1,
        "caller": "saayam",
    })
    if listing is None:
        return []
    try:
        features = _features(listing)
        if len(features) >= PAGE_SIZE:
            # A full page may have left fires on the next one, and a fire
            # that is not looked at cannot be reported.
            raise FeedError(f"GDACS returned a full page of {PAGE_SIZE}; the list may be incomplete")
        return [_fire(feature) for feature in features]
    except (KeyError, TypeError, ValueError, OverflowError) as e:
        raise FeedError(f"GDACS payload was not in the expected shape: {type(e).__name__}: {e}") from e


def _get(url, params):
    """The decoded JSON object, or None when GDACS answers 204 No Content.

    GDACS answers a search with nothing to report with an empty 204, not an
    empty list. None is reserved for that: any other answer has to be a JSON
    object, or a 200 whose body is a bare ``null`` would read as "nothing".
    """
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "saayam-disaster-check"},
    )
    try:
        # The URLs are module constants, so the scheme is always https.
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310
            if response.status == 204:
                return None
            body = response.read()
    except (OSError, http.client.HTTPException) as e:
        # GDACS reports its own overload as a 400, and a fire or update it does
        # not know as a 404 or a 400, so every HTTP error counts.
        raise FeedUnreachable(f"GDACS request failed: {type(e).__name__}: {e}") from e
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except ValueError as e:
        raise FeedError(f"GDACS answer is not JSON: {e}") from e
    if not isinstance(payload, dict):
        raise FeedError(f"GDACS answered with a JSON {type(payload).__name__}, not an object")
    return payload


def _features(payload):
    # Anything other than a list would iterate as "no fires".
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("no list of features")
    return features


def _fire(feature):
    properties = feature["properties"]
    # A flood listed here would be read as a fire, and its affected area
    # would never be found.
    if properties["eventtype"] != EVENT_TYPE:
        raise ValueError(f"listed as a {properties['eventtype']!r} event, not a wildfire")
    longitude, latitude = feature["geometry"]["coordinates"][:2]
    # The level of the latest update, which is where the fire stands now. The
    # fire's own level is the highest it has reached.
    alert_level = properties["episodealertlevel"]
    if alert_level not in SEVERITY:
        raise ValueError(f"unknown alert level {alert_level!r}")
    running = properties["iscurrent"]
    if running not in ("true", "false"):
        raise ValueError(f"iscurrent is {running!r}")
    return {
        "event_id": _whole(properties["eventid"]),
        "episode_id": _whole(properties["episodeid"]),
        "alert_level": alert_level,
        "name": str(properties["name"]),
        "latitude": _real(latitude, -90, 90),
        "longitude": _real(longitude, -180, 180),
        "running": running == "true",
        "started_at": _utc(properties["fromdate"]),
        # GDACS dates a fire by whole days, and the fire burned during its
        # last one: it ends at the end of that day, not the start.
        "ended_at": _end_of_day(properties["todate"]),
    }


def _burned_area(fire):
    """The burned area GDACS publishes for one fire, as a MultiPolygon.

    Requested by ID, and every feature in the answer must carry that fire's
    type and IDs, as for floods, where GDACS answered a request for an ID it
    did not know with another event's geometry. The burned area is the
    ``Poly_area`` feature: asked for ``polygontype=Affected``, as floods are,
    GDACS answers with the fire's centre point alone.

    Only the outline of each polygon is kept. Its holes are unburned ground
    surrounded by fire, which is in the fire zone.
    """
    payload = _get(GEOMETRY_URL, {
        "eventtype": EVENT_TYPE,
        "eventid": fire["event_id"],
        "episodeid": fire["episode_id"],
        "polygontype": "area",
    })
    wanted = (EVENT_TYPE, fire["event_id"], fire["episode_id"])
    polygons = []
    for feature in _features(payload) if payload is not None else []:
        properties = feature["properties"]
        answered = (properties["eventtype"], properties["eventid"], properties["episodeid"])
        if answered != wanted:
            raise ValueError(f"asked for fire {wanted}, answered for {answered}")
        if properties.get("Class") != "Poly_area":
            continue
        geometry = feature["geometry"]
        if geometry["type"] == "Polygon":
            polygons.append(geometry["coordinates"])
        elif geometry["type"] == "MultiPolygon":
            polygons.extend(geometry["coordinates"])
        else:
            raise ValueError(f"burned area is a {geometry['type']!r}")
    if not polygons:
        # Without the area there is no telling who is in the fire, and
        # leaving the fire out could tell someone in it that nothing is
        # happening.
        raise ValueError(f"no burned area published for fire {wanted}")
    area = []
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError("a burned polygon has no rings")
        rings = []
        # Every ring is checked, holes included, so a damaged answer fails
        # however little of it is used.
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("a burned ring has fewer than four positions")
            rings.append([_position(position) for position in ring])
        _require_outline_first(rings)
        area.append(rings[:1])
    return {"type": "MultiPolygon", "coordinates": area}


def _require_outline_first(rings):
    """GeoJSON lists a polygon's outline first, then its holes.

    Only the first ring is kept, so a hole listed first would become the
    whole zone and leave the burned ground around it outside. Every other
    ring must lie within the first one's bounds, which a hole listed first
    never does.
    """
    longitudes = [longitude for longitude, _ in rings[0]]
    latitudes = [latitude for _, latitude in rings[0]]
    west, east, south, north = min(longitudes), max(longitudes), min(latitudes), max(latitudes)
    for ring in rings[1:]:
        if not all(west <= longitude <= east and south <= latitude <= north for longitude, latitude in ring):
            raise ValueError("a burned polygon's first ring is not its outline")


def _position(position):
    """[longitude, latitude] as finite numbers, dropping anything after them."""
    if not isinstance(position, list) or len(position) < 2:
        raise ValueError(f"{position!r} is not a position")
    return [_real(position[0], -180, 180), _real(position[1], -90, 90)]


def _event(fire, area):
    report = urllib.parse.urlencode({
        "eventid": fire["event_id"],
        "episodeid": fire["episode_id"],
        "eventtype": EVENT_TYPE,
    })
    return {
        "event_id": f"gdacs-WF-{fire['event_id']}",
        "event_type": "wildfire",
        "severity": SEVERITY[fire["alert_level"]],
        "headline": f"{fire['alert_level']} wildfire alert: {fire['name']}",
        "started_at": fire["started_at"],
        # Open while GDACS reports the fire as burning: its end date is then
        # only the date of its latest update.
        "expires_at": None if fire["running"] else fire["ended_at"],
        "latitude": fire["latitude"],
        "longitude": fire["longitude"],
        "area": area,
        # The centre-and-radius fallback has to cover the whole area.
        "radius_km": farthest_km(fire["latitude"], fire["longitude"], area),
        "volunteer_band_km": VOLUNTEER_BAND_KM,
        # The burned area is observed from satellites, and Orange and Red
        # levels are set with expert review.
        "confidence": "high",
        "url": f"{REPORT_URL}?{report}",
    }


def _end_of_day(text):
    """The end of the day a date names, in UTC.

    Taken before converting, so a date written with a zone ends when that
    zone's day ends, not when the UTC day does.
    """
    moment = _moment(text)
    return _as_utc(moment.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))


def _real(value, low, high):
    """A finite number within bounds, or ValueError.

    The JSON parser accepts NaN and Infinity, and a NaN coordinate would fail
    every comparison that places the fire.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{value!r} is not a number between {low} and {high}")
    return float(value)


def _whole(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{value!r} is not an ID")
    return value


def _utc(text):
    return _as_utc(_moment(text))


def _moment(text):
    if not isinstance(text, str):
        raise ValueError(f"{text!r} is not a date")
    return datetime.fromisoformat(text)


def _as_utc(moment):
    # GDACS writes its times without a zone. They are UTC.
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
