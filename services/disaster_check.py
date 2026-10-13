"""Disaster check: is a natural disaster affecting a location? - issue #191.

Authoritative feeds decide. Nothing in this module asks a model anything: an
event exists here only because a feed in ``FEEDS`` listed it, and every event
carries that feed in ``verified_by``.

This is the coordinate half of the service. The news-snippet half, and the LLM
cross-check that goes with it, are not built yet.
"""
import math
from datetime import datetime, timedelta, timezone

from services import usgs_earthquakes

# One adapter per authoritative feed. See services/usgs_earthquakes.py for the
# four names an adapter has to expose.
FEEDS = (usgs_earthquakes,)

DEFAULT_RADIUS_KM = 50.0
MAX_RADIUS_KM = 500.0
DEFAULT_WINDOW_HOURS = 72.0
# A feed takes minutes to publish an event, so a window much shorter than
# this could only ever answer "nothing".
MIN_WINDOW_HOURS = 1.0
MAX_WINDOW_HOURS = 168.0

EARTH_RADIUS_KM = 6371.0088
_CIRCLE_POINTS = 32
_SEVERITY_RANK = {"minor": 0, "moderate": 1, "severe": 2, "extreme": 3}


class InvalidQuery(ValueError):
    """The caller's parameters cannot be used. The message is safe to return."""


class DisasterCheckUnavailable(Exception):
    """A feed did not answer, so there is no negative finding to report."""


def parse_query(body):
    """Validate a coordinate query and apply the defaults."""
    if body.get("latitude") in (None, "") or body.get("longitude") in (None, ""):
        raise InvalidQuery("latitude and longitude are required")
    return {
        "latitude": _number(body, "latitude", -90, 90),
        "longitude": _number(body, "longitude", -180, 180),
        "radius_km": _number(body, "radius_km", 0, MAX_RADIUS_KM, DEFAULT_RADIUS_KM, above_low=True),
        "window_hours": _number(body, "window_hours", MIN_WINDOW_HOURS, MAX_WINDOW_HOURS, DEFAULT_WINDOW_HOURS),
    }


def _number(body, key, low, high, default=None, above_low=False):
    value = body.get(key)
    if value in (None, ""):
        value = default
    # bool is an int in Python, and True must not be read as a latitude of 1.
    if isinstance(value, bool):
        raise InvalidQuery(f"{key} must be a number")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise InvalidQuery(f"{key} must be a number") from None
    except OverflowError:
        # An integer too large for a float is out of range, not unreadable.
        value = math.inf
    # NaN fails every comparison, so it is caught by the range check too.
    if not (low <= value <= high) or (above_low and value == low):
        bounds = f"greater than {low:g} and at most {high:g}" if above_low else f"between {low:g} and {high:g}"
        raise InvalidQuery(f"{key} must be {bounds}")
    return value


def check_location(latitude, longitude, radius_km, window_hours, now=None):
    """Events whose impact zone reaches the circle around a point.

    A detection stands on the feed that made it. A negative answer needs
    every feed to have answered: if any did not and nothing was found, this
    raises DisasterCheckUnavailable rather than hand the caller
    ``disaster_detected: false`` for an event type nobody was asked about.
    """
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)
    retrieved_at = _iso(now)

    events = []
    sources_checked = []
    for feed in FEEDS:
        # A large event far away can still cover the caller, so the feed is
        # asked about a wider circle than the caller's and the events are
        # narrowed below, once each one's own zone is known.
        search_radius_km = radius_km + feed.MAX_IMPACT_RADIUS_KM
        source = {"source": feed.SOURCE, "event_types": list(feed.EVENT_TYPES)}
        try:
            found = feed.fetch_events(latitude, longitude, search_radius_km, since)
        except Exception as e:
            # Fail closed: anything a feed raises, including a bug in its
            # adapter, is an unanswered question rather than an empty answer.
            print(f"ERROR: disaster_check feed {feed.SOURCE} failed: {type(e).__name__}: {e}")
            sources_checked.append({**source, "status": "unavailable"})
            continue
        sources_checked.append({**source, "status": "ok", "retrieved_at": retrieved_at})
        for event in found:
            distance = distance_km(latitude, longitude, event["latitude"], event["longitude"])
            if distance <= radius_km + event["radius_km"]:
                events.append((event, feed.SOURCE))

    unavailable = [source["source"] for source in sources_checked if source["status"] != "ok"]
    if unavailable and not events:
        raise DisasterCheckUnavailable(f"no answer from: {', '.join(unavailable)}")

    events.sort(
        key=lambda found: (_SEVERITY_RANK[found[0]["severity"]], found[0]["radius_km"]),
        reverse=True,
    )
    return {
        "disaster_detected": bool(events),
        # The grade of the first event, the one a caller acts on - not the
        # best grade in the list, or a reviewed aftershock would vouch for an
        # unreviewed mainshock. With nothing detected there is nothing to
        # grade; sources_checked says what the negative answer covers.
        "confidence": events[0][0]["confidence"] if events else None,
        "events": [_render(event, source, retrieved_at) for event, source in events],
        "sources_checked": sources_checked,
    }


def _render(event, source, retrieved_at):
    radius_km = round(event["radius_km"], 1)
    return {
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "severity": event["severity"],
        "headline": event["headline"],
        "started_at": _iso(event["started_at"]),
        "expires_at": _iso(event["expires_at"]),
        "impact_zone": circle_polygon(event["latitude"], event["longitude"], event["radius_km"]),
        # [latitude, longitude], as in the issue's contract - the opposite
        # order to the GeoJSON positions in impact_zone.
        "impact_zone_fallback": {
            "center": [event["latitude"], event["longitude"]],
            "radius_km": radius_km,
        },
        "boundary_source": "modelled",
        "verified_by": [{"source": source, "url": event["url"], "retrieved_at": retrieved_at}],
        # No model runs on the coordinate path, so there is nothing to report.
        "llm_cross_check": None,
        "volunteer_band_km": event["volunteer_band_km"],
        "advisory": (
            f"{event['headline']}, reported by {source}. The impact zone is a "
            f"modelled circle of about {radius_km:g} km, not an observed boundary."
        ),
    }


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points (haversine)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    half_dphi = (phi2 - phi1) / 2
    half_dlambda = math.radians(lon2 - lon1) / 2
    a = math.sin(half_dphi) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(half_dlambda) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def circle_polygon(latitude, longitude, radius_km):
    """A circle on the globe as a GeoJSON Polygon.

    The ring is counterclockwise, as RFC 7946 asks of an exterior ring.
    Longitudes are deliberately left unwrapped: a zone that crosses the
    antimeridian has vertices past +/-180 rather than a ring that jumps to the
    far side of the map. ``impact_zone_fallback`` is the exact form.
    """
    phi1 = math.radians(latitude)
    lambda1 = math.radians(longitude)
    # The vertices sit just outside the circle so that the edges touch it. A
    # ring through points on the circle would cut inside it between them and
    # leave out people the radius includes.
    delta = radius_km / EARTH_RADIUS_KM / math.cos(math.pi / _CIRCLE_POINTS)

    ring = []
    for i in range(_CIRCLE_POINTS):
        bearing = -2 * math.pi * i / _CIRCLE_POINTS
        # Clamped because a vertex landing on a pole can come out one rounding
        # step past 1, which asin refuses.
        phi2 = math.asin(max(-1.0, min(1.0, (
            math.sin(phi1) * math.cos(delta)
            + math.cos(phi1) * math.sin(delta) * math.cos(bearing)
        ))))
        lambda2 = lambda1 + math.atan2(
            math.sin(bearing) * math.sin(delta) * math.cos(phi1),
            math.cos(delta) - math.sin(phi1) * math.sin(phi2),
        )
        ring.append([round(math.degrees(lambda2), 4), round(math.degrees(phi2), 4)])
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}
