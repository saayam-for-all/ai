"""Disaster check: is a natural disaster affecting a location? - issue #191.

Authoritative feeds decide. Nothing in this module asks a model anything: an
event exists here only because a feed in ``FEEDS`` listed it, and every event
carries that feed in ``verified_by``.

This is the coordinate half of the service. The news-snippet half, and the LLM
cross-check that goes with it, are not built yet.
"""
import math
from datetime import timedelta, timezone

from services import feed_cache, gdacs_floods, usgs_earthquakes
from services.geometry import circle_polygon, distance_km, distance_to_area_km

# One adapter per authoritative feed. See services/usgs_earthquakes.py for the
# four names an adapter has to expose.
FEEDS = (usgs_earthquakes, gdacs_floods)

DEFAULT_RADIUS_KM = 50.0
MAX_RADIUS_KM = 500.0
DEFAULT_WINDOW_HOURS = 72.0
# A feed takes minutes to publish an event, so a window much shorter than
# this could only ever answer "nothing".
MIN_WINDOW_HOURS = 1.0
MAX_WINDOW_HOURS = 168.0

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
    now = now or feed_cache.utcnow()
    since = now - timedelta(hours=window_hours)

    events = []
    sources_checked = []
    for feed in FEEDS:
        # A large event far away can still cover the caller, so the feed is
        # asked about a wider circle than the caller's and the events are
        # narrowed below, once each one's own zone is known.
        search_radius_km = radius_km + feed.MAX_IMPACT_RADIUS_KM
        source = {"source": feed.SOURCE, "event_types": list(feed.EVENT_TYPES)}
        try:
            answer = feed.fetch_events(latitude, longitude, search_radius_km, since)
            for event in answer.events:
                _require_known_severity(event)
            # Matched inside the guard as well, so an event this module cannot
            # use takes down its own feed rather than the whole request.
            reached = [event for event in answer.events if _reaches(event, latitude, longitude, radius_km)]
            # When the feed actually answered, which for a cached answer is
            # earlier than this request. A stale answer is one used because
            # the feed could not be reached; it still counts as an answer.
            retrieved_at = _iso(answer.retrieved_at)
        except Exception as e:
            # Fail closed: anything a feed raises, including a bug in its
            # adapter, is an unanswered question rather than an empty answer.
            print(f"ERROR: disaster_check feed {feed.SOURCE} failed: {type(e).__name__}: {e}")
            sources_checked.append({**source, "status": "unavailable"})
            continue
        status = "stale" if answer.stale else "ok"
        sources_checked.append({**source, "status": status, "retrieved_at": retrieved_at})
        events += [(event, feed.SOURCE, retrieved_at) for event in reached]

    unavailable = [source["source"] for source in sources_checked if source["status"] == "unavailable"]
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
        "events": [_render(event, source, retrieved_at) for event, source, retrieved_at in events],
        "sources_checked": sources_checked,
    }


def _require_known_severity(event):
    """Adapters map their feed's own scale onto the four values ranked here.

    A fifth value, such as CAP's "Unknown", means the feed has not been read
    properly yet. It fails here, as that feed being unavailable, rather than
    in the sort as a 500 that takes every other feed's findings with it.
    """
    if event["severity"] not in _SEVERITY_RANK:
        raise ValueError(f"severity {event['severity']!r} is not one of {sorted(_SEVERITY_RANK)}")


def _reaches(event, latitude, longitude, radius_km):
    """Whether an event's impact zone comes within radius_km of the point.

    An event with an ``area`` - a boundary the feed itself publishes - is
    judged by that boundary. Any other is a modelled circle around a centre.
    """
    if event.get("area"):
        return distance_to_area_km(latitude, longitude, event["area"]) <= radius_km
    return distance_km(latitude, longitude, event["latitude"], event["longitude"]) <= radius_km + event["radius_km"]


def _render(event, source, retrieved_at):
    area = event.get("area")
    # Around a published area the fallback circle must cover all of it, so its
    # radius is rounded up rather than to the nearest 100 m.
    radius_km = math.ceil(event["radius_km"] * 10) / 10 if area else round(event["radius_km"], 1)
    if area:
        advisory = f"The impact zone is the affected area published by {source}."
    else:
        advisory = (
            f"The impact zone is a modelled circle of about {radius_km:g} km, "
            "not an observed boundary."
        )
    return {
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "severity": event["severity"],
        "headline": event["headline"],
        "started_at": _iso(event["started_at"]),
        "expires_at": _iso(event["expires_at"]) if event["expires_at"] else None,
        "impact_zone": area or circle_polygon(event["latitude"], event["longitude"], event["radius_km"]),
        # [latitude, longitude], as in the issue's contract - the opposite
        # order to the GeoJSON positions in impact_zone. Around a published
        # area, the adapter sizes this circle to cover all of it.
        "impact_zone_fallback": {
            "center": [event["latitude"], event["longitude"]],
            "radius_km": radius_km,
        },
        "boundary_source": "authoritative" if area else "modelled",
        "verified_by": [{"source": source, "url": event["url"], "retrieved_at": retrieved_at}],
        # No model runs on the coordinate path, so there is nothing to report.
        "llm_cross_check": None,
        "volunteer_band_km": event["volunteer_band_km"],
        "advisory": f"{event['headline']}, reported by {source}. {advisory}",
    }


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
