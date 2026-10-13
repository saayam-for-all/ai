"""USGS earthquake feed adapter for disaster_check - issue #191.

The authoritative source for earthquakes. It is public and takes no API key,
so this module has no credential to load and nothing to import beyond the
standard library.

Every feed adapter exposes the same four names, which is all
``services.disaster_check`` relies on:

    SOURCE                the name recorded in ``verified_by``
    EVENT_TYPES           the event types an answer from this feed covers
    MAX_IMPACT_RADIUS_KM  the widest zone one of its events can have
    fetch_events          the query, returning feed-neutral event records

A flood or wildfire adapter is a second module with the same four names,
added to ``services.disaster_check.FEEDS``.
"""
import http.client
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

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


class FeedError(Exception):
    """The feed could not be reached, or answered with something unusable."""


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
    """Earthquakes at or above MIN_MAGNITUDE near a point since a moment.

    Raises FeedError when the feed is unreachable or its answer cannot be
    read. An empty list is therefore a real answer - the feed was asked and
    listed nothing - and never a stand-in for a failure.
    """
    query = urllib.parse.urlencode({
        "format": "geojson",
        "eventtype": "earthquake",
        "latitude": latitude,
        "longitude": longitude,
        "maxradiuskm": search_radius_km,
        "minmagnitude": MIN_MAGNITUDE,
        "starttime": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "orderby": "magnitude",
    })
    request = urllib.request.Request(
        f"{QUERY_URL}?{query}",
        headers={"User-Agent": "saayam-disaster-check"},
    )
    try:
        # QUERY_URL is a module constant, so the scheme is always https.
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310
            payload = json.load(response)
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise FeedError(f"USGS query failed: {type(e).__name__}: {e}") from e

    # One unreadable feature fails the whole answer. Skipping it instead could
    # drop the only event in the response and turn it into an all-clear.
    try:
        return [_to_event(feature) for feature in payload["features"]]
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as e:
        raise FeedError(f"USGS payload was not in the expected shape: {type(e).__name__}: {e}") from e


def _to_event(feature):
    properties = feature["properties"]
    longitude, latitude = feature["geometry"]["coordinates"][:2]
    magnitude = float(properties["mag"])
    started_at = datetime.fromtimestamp(properties["time"] / 1000, tz=timezone.utc)
    return {
        "event_id": f"usgs-{feature['id']}",
        "event_type": "earthquake",
        "severity": severity_for(magnitude),
        "headline": str(properties["title"]),
        "started_at": started_at,
        "expires_at": started_at + timedelta(hours=ALERT_LIFETIME_HOURS),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "radius_km": impact_radius_km(magnitude),
        "volunteer_band_km": VOLUNTEER_BAND_KM,
        # A seismologist has reviewed the solution. Automatic solutions are
        # published within minutes and are revised, occasionally withdrawn.
        "confidence": "high" if properties.get("status") == "reviewed" else "medium",
        "url": str(properties["url"]),
    }
