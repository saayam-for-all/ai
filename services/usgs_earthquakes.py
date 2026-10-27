"""USGS earthquake feed adapter for disaster_check - issue #191.

The authoritative source for earthquakes. It is public and takes no API key,
so this module has no credential to load.

Every feed adapter exposes the same four names, which is all
``services.disaster_check`` relies on:

    SOURCE                the name recorded in ``verified_by``
    EVENT_TYPES           the event types an answer from this feed covers
    MAX_IMPACT_RADIUS_KM  the widest zone one of its events can have
    fetch_events          the query, returning a feed_cache.FeedAnswer: the
                          feed-neutral event records, when the feed actually
                          answered, and whether that answer is stale

A flood or wildfire adapter is a second module with the same four names,
added to ``services.disaster_check.FEEDS``.

USGS is asked once for every earthquake worldwide in the window, and that one
answer is cached and shared by every caller; disaster_check keeps the events
that reach each caller. A query per location could not be shared.
"""
import http.client
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from services import feed_cache

SOURCE = "USGS"
EVENT_TYPES = ("earthquake",)

QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
TIMEOUT_SECONDS = 8

# Below this an earthquake is felt but very rarely damaging. The issue is
# explicit that a wrong alert costs more than a missed minor one, so the
# feed is never asked for anything smaller.
MIN_MAGNITUDE = 5.0

# The modelled radius is capped here (reached at magnitude 9.0). The cap is
# also how far beyond the caller's radius disaster_check has to search for an
# epicentre whose impact zone could still reach the caller.
MAX_IMPACT_RADIUS_KM = 1000.0

# How long after the origin time an earthquake is still treated as a live
# event, and how far outside the impact zone volunteers are worth calling on.
# Both are first-pass values awaiting review - see the README.
ALERT_LIFETIME_HOURS = 72
VOLUNTEER_BAND_KM = 50

# An earthquake can happen at any minute, so the worldwide answer is reused
# for one minute at most and never once USGS stops answering. A first-pass
# value awaiting review - see the README.
FRESH_SECONDS = 60

# The shared answer reaches this far back, the longest window disaster_check
# accepts, so one answer serves every caller whatever their window. A window
# reaching further back is asked for on its own.
COVER_HOURS = 168

_ANSWERS = feed_cache.FeedCache(fresh_seconds=FRESH_SECONDS, stale_seconds=0, max_entries=1)


class FeedError(Exception):
    """The feed could not be reached, or answered with something unusable."""


class FeedUnreachable(FeedError, feed_cache.Unreachable):
    """USGS could not be reached: a network error, a timeout or an HTTP error."""


def impact_radius_km(magnitude):
    """Modelled radius of the impact zone around the epicentre.

    A first-pass heuristic, not a shaking model: log10(radius) = 0.5 M - 1.5,
    which gives 10 km at M5, about 32 km at M6, 100 km at M7 and about 316 km
    at M8. It ignores depth, fault geometry, soil and building stock, which is
    why every zone built from it is labelled ``boundary_source: "modelled"``.
    """
    return min(10 ** (0.5 * magnitude - 1.5), MAX_IMPACT_RADIUS_KM)


def severity_for(magnitude):
    """Severity in the CAP vocabulary, so every event type can share one scale."""
    if magnitude >= 7.0:
        return "extreme"
    if magnitude >= 6.0:
        return "severe"
    return "moderate"


def fetch_events(latitude, longitude, search_radius_km, since):
    """Earthquakes at or above MIN_MAGNITUDE anywhere, since a moment.

    The location is not sent to USGS: the worldwide answer is shared, and
    disaster_check keeps the events whose zone reaches the caller. Raises
    FeedError when the feed is unreachable or its answer cannot be read, or
    feed_cache.BackingOff in the minute after a failure. No events is a real
    answer - the feed was asked and listed nothing - never a stand-in for a
    failure.
    """
    answer = _ANSWERS.get("worldwide", _shared)
    start, events = answer.value
    retrieved_at, stale = answer.fetched_at, answer.stale
    if since < start:
        start = _hour(since)
        events, retrieved_at, stale = _worldwide(start), feed_cache.utcnow(), False
    # The answer starts at an hour, at or before the window; this puts the
    # window's own edge back exactly.
    events = [event for event in events if event["started_at"] >= since]
    return feed_cache.FeedAnswer(events, retrieved_at, stale)


def _shared():
    start = _hour(feed_cache.utcnow() - timedelta(hours=COVER_HOURS))
    return start, _worldwide(start)


def _hour(moment):
    return moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _worldwide(start):
    # No limit is sent: USGS refuses a search that would match more than
    # 20,000 events rather than cutting it short, so an answer is never
    # silently incomplete.
    query = urllib.parse.urlencode({
        "format": "geojson",
        "eventtype": "earthquake",
        "minmagnitude": MIN_MAGNITUDE,
        "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "orderby": "magnitude",
    })
    request = urllib.request.Request(
        f"{QUERY_URL}?{query}",
        headers={"User-Agent": "saayam-disaster-check"},
    )
    try:
        # QUERY_URL is a module constant, so the scheme is always https.
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310
            body = response.read()
    except (OSError, http.client.HTTPException) as e:
        raise FeedUnreachable(f"USGS query failed: {type(e).__name__}: {e}") from e
    try:
        payload = json.loads(body)
    except ValueError as e:
        raise FeedError(f"USGS answer is not JSON: {e}") from e

    # Anything other than a list here would iterate as "no events": an empty
    # object or string yields nothing, and nothing is an all-clear.
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise FeedError("USGS payload has no list of features")

    # One unreadable feature fails the whole answer. Skipping it instead could
    # drop the only event in the response and turn it into an all-clear.
    try:
        return [_to_event(feature) for feature in features]
    except (KeyError, TypeError, ValueError) as e:
        raise FeedError(f"USGS payload was not in the expected shape: {type(e).__name__}: {e}") from e


def _real(value, low, high):
    """A finite number within bounds, or ValueError.

    The JSON parser accepts NaN and Infinity. A NaN magnitude or coordinate
    makes every comparison downstream false, so the event would not be
    rejected - it would quietly never match any caller.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{value!r} is not a number between {low} and {high}")
    return float(value)


def _to_event(feature):
    properties = feature["properties"]
    longitude, latitude = feature["geometry"]["coordinates"][:2]
    latitude = _real(latitude, -90, 90)
    longitude = _real(longitude, -180, 180)
    magnitude = _real(properties["mag"], 0, 10)
    # Milliseconds since 1970, bounded at the year 2100 so the conversion
    # cannot overflow on any platform.
    started_at = datetime.fromtimestamp(_real(properties["time"], 0, 4_102_444_800_000) / 1000, tz=timezone.utc)
    return {
        "event_id": f"usgs-{feature['id']}",
        "event_type": "earthquake",
        "severity": severity_for(magnitude),
        "headline": str(properties["title"]),
        "started_at": started_at,
        "expires_at": started_at + timedelta(hours=ALERT_LIFETIME_HOURS),
        "latitude": latitude,
        "longitude": longitude,
        "radius_km": impact_radius_km(magnitude),
        "volunteer_band_km": VOLUNTEER_BAND_KM,
        # A seismologist has reviewed the solution. Automatic solutions are
        # published within minutes and are revised, occasionally withdrawn.
        # Some networks write the status in capitals.
        "confidence": "high" if str(properties.get("status")).lower() == "reviewed" else "medium",
        "url": str(properties["url"]),
    }
