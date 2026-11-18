"""GDACS flood feed adapter for disaster_check - issue #191, part 2.

GDACS, the Global Disaster Alert and Coordination System, is run by the UN
(OCHA) and the European Commission's Joint Research Centre. Its flood alerts
come from GloFAS river forecasts. The API is public and takes no key.

GDACS publishes no magnitude for a flood, and the affected areas measured
while building this reach anywhere from 5 km to 567 km from the centre GDACS
gives, with no link to the alert level. No circle drawn from that centre would
be right, so each flood's zone is the affected area GDACS publishes for it,
reported as ``boundary_source: "authoritative"``.

Exposes the same four names as services/usgs_earthquakes.py.
"""
import http.client
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from services.geometry import distance_km, farthest_km

SOURCE = "GDACS"
EVENT_TYPES = ("flood",)

LIST_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GEOMETRY_URL = "https://www.gdacs.org/gdacsapi/api/polygons/getgeometry"
REPORT_URL = "https://www.gdacs.org/report.aspx"
TIMEOUT_SECONDS = 8
# The most floods GDACS returns in one page of results.
PAGE_SIZE = 100

# GDACS grades every flood Green, Orange or Red by expected humanitarian
# impact. Green, "low impact", was 98 of the 100 most recent floods, and the
# issue holds a false alert to be worse than silence, so only Orange and Red
# are reported. A first-pass value awaiting review - see the README.
ALERT_LEVELS = ("Orange", "Red")
SEVERITY = {"Green": "minor", "Orange": "severe", "Red": "extreme"}

# GDACS updates a running flood every one to nine days, and until the next
# update its end date is the date of the last one. The list is asked for
# from this much earlier than the window, so a flood that is still running
# is not dropped for an end date that has not caught up.
LOOKBACK_DAYS = 10

# Only floods whose centre is within this distance of the caller's circle
# have their affected area fetched. The farthest any affected area reached
# from its centre, across 24 floods measured in October 2026, was 567 km.
MAX_IMPACT_RADIUS_KM = 1000.0

# The value the issue's own flood example uses. Awaiting review.
VOLUNTEER_BAND_KM = 30


class FeedError(Exception):
    """The feed could not be reached, or answered with something unusable."""


def fetch_events(latitude, longitude, search_radius_km, since):
    """Orange and Red floods running at any time since a moment, near a point.

    Raises FeedError when GDACS is unreachable or its answer cannot be read,
    including when a nearby flood's affected area cannot be fetched. An empty
    list is therefore a real answer: GDACS was asked and listed nothing.
    """
    listing = _get(LIST_URL, {
        "eventlist": "FL",
        "alertlevel": ";".join(ALERT_LEVELS),
        # GDACS returns the floods whose end date is on or after this date.
        "fromDate": (since - timedelta(days=LOOKBACK_DAYS)).astimezone(timezone.utc).strftime("%Y-%m-%d"),
        "pageSize": PAGE_SIZE,
        "pageNumber": 1,
        "caller": "saayam",
    })
    if listing is None:
        return []

    try:
        features = _features(listing)
        if len(features) >= PAGE_SIZE:
            # A full page may have left floods on the next one, and a flood
            # that is not looked at cannot be reported.
            raise FeedError(f"GDACS returned a full page of {PAGE_SIZE}; the list may be incomplete")
        events = []
        for feature in features:
            flood = _flood(feature)
            if flood["alert_level"] not in ALERT_LEVELS:
                continue
            if not flood["running"] and flood["ended_at"] < since:
                continue
            if distance_km(latitude, longitude, flood["latitude"], flood["longitude"]) > search_radius_km:
                continue
            events.append(_event(flood, _affected_area(flood)))
        return events
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
            payload = json.loads(response.read().decode("utf-8-sig"))
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise FeedError(f"GDACS request failed: {type(e).__name__}: {e}") from e
    if not isinstance(payload, dict):
        raise FeedError(f"GDACS answered with a JSON {type(payload).__name__}, not an object")
    return payload


def _features(payload):
    # Anything other than a list would iterate as "no floods".
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("no list of features")
    return features


def _flood(feature):
    properties = feature["properties"]
    longitude, latitude = feature["geometry"]["coordinates"][:2]
    # A flood's own alert level is the highest it has ever reached. The
    # episode's level is where it stands at the latest update, and that is
    # what an alert sent now is about: a flood that was Orange for a day and
    # Green for weeks after is not reported for those weeks.
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
        "ended_at": _utc(properties["todate"]),
    }


def _affected_area(flood):
    """The affected area GDACS publishes for one flood, as a MultiPolygon.

    The geometry is requested by ID rather than through the URL in the
    listing, and every feature in the answer must carry that ID: GDACS answers
    a request for an ID it does not know with another event's geometry.
    """
    payload = _get(GEOMETRY_URL, {
        "eventtype": "FL",
        "eventid": flood["event_id"],
        "episodeid": flood["episode_id"],
        "polygontype": "Affected",
    })
    wanted = (flood["event_id"], flood["episode_id"])
    polygons = []
    for feature in _features(payload) if payload is not None else []:
        properties = feature["properties"]
        if (properties["eventid"], properties["episodeid"]) != wanted:
            raise ValueError(f"asked for flood {wanted}, answered for {(properties['eventid'], properties['episodeid'])}")
        if properties.get("Class") != "Poly_Affected":
            continue
        geometry = feature["geometry"]
        if geometry["type"] == "Polygon":
            polygons.append(geometry["coordinates"])
        elif geometry["type"] == "MultiPolygon":
            polygons.extend(geometry["coordinates"])
        else:
            raise ValueError(f"affected area is a {geometry['type']!r}")
    if not polygons:
        # Without the area there is no telling who is in the flood, and
        # leaving the flood out could tell someone in it that nothing is
        # happening.
        raise ValueError(f"no affected area published for flood {wanted}")
    area = []
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError("an affected polygon has no rings")
        rings = []
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("an affected ring has fewer than four positions")
            rings.append([_position(position) for position in ring])
        area.append(rings)
    return {"type": "MultiPolygon", "coordinates": area}


def _position(position):
    """[longitude, latitude] as finite numbers, dropping anything after them.

    An altitude is not used, and passing one through unchecked could put a
    NaN into the response, which is not valid JSON.
    """
    if not isinstance(position, list) or len(position) < 2:
        raise ValueError(f"{position!r} is not a position")
    return [_real(position[0], -180, 180), _real(position[1], -90, 90)]


def _event(flood, area):
    report = urllib.parse.urlencode({
        "eventid": flood["event_id"],
        "episodeid": flood["episode_id"],
        "eventtype": "FL",
    })
    return {
        "event_id": f"gdacs-FL-{flood['event_id']}",
        "event_type": "flood",
        "severity": SEVERITY[flood["alert_level"]],
        "headline": f"{flood['alert_level']} flood alert: {flood['name']}",
        "started_at": flood["started_at"],
        # Open while GDACS reports the flood as running: its end date is then
        # only the date of its latest update, and a client that read it as an
        # expiry would stop alerting about a flood that is still going.
        "expires_at": None if flood["running"] else flood["ended_at"],
        "latitude": flood["latitude"],
        "longitude": flood["longitude"],
        "area": area,
        # The centre-and-radius fallback has to cover the whole area.
        "radius_km": farthest_km(flood["latitude"], flood["longitude"], area),
        "volunteer_band_km": VOLUNTEER_BAND_KM,
        # GDACS flood alerts are GloFAS forecasts, not observations.
        "confidence": "medium",
        "url": f"{REPORT_URL}?{report}",
    }


def _real(value, low, high):
    """A finite number within bounds, or ValueError.

    The JSON parser accepts NaN and Infinity, and a NaN coordinate would fail
    every comparison that places the flood.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{value!r} is not a number between {low} and {high}")
    return float(value)


def _whole(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{value!r} is not an ID")
    return value


def _utc(text):
    if not isinstance(text, str):
        raise ValueError(f"{text!r} is not a date")
    moment = datetime.fromisoformat(text)
    # GDACS writes its times without a zone. They are UTC.
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
