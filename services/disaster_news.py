"""Part 4: conservative English news extraction and USGS record matching.

This intentionally supports a small, explicit report grammar. Other prose
is unresolved, not evidence. Part 5 can extend extraction/corroboration using
the structured `extracted` result; no model has verified anything here.
"""
import re
from datetime import datetime, timedelta, timezone

from services import disaster_check as dc, disaster_geocoding, usgs_earthquakes

MAX_SNIPPET_LENGTH = 2000
MATCH_DISTANCE_KM = 50.0
MATCH_TIME = timedelta(minutes=15)
MAGNITUDE_TOLERANCE = 0.3
_CLOCK = r"(?:[01]\d|2[0-3]):[0-5]\d"
_TIMESTAMP = r"\d{4}-\d{2}-\d{2}T" + _CLOCK + r"(?::[0-5]\d)?(?:Z|[+-]" + _CLOCK + r")"
_REPORT = re.compile(
    r"(?:A\s+)?(?:magnitude\s+|M\s*)(?P<magnitude>\d+(?:\.\d+)?)\s+"
    r"earthquake\s+(?:struck|hit|occurred)\s+(?:near|in)\s+"
    r"(?P<place>[^.;!?\n]+?)(?:\s+(?:on|at)\s+(?P<time>" + _TIMESTAMP + r"|\d{4}-\d{2}-\d{2})"
    r"|\s+(?P<relative>today|yesterday|this morning))?\.?",
    re.IGNORECASE,
)
_TYPES = {
    "earthquake": r"\b(?:earthquakes?|quakes?)\b",
    "flood": r"\bflood(?:s|ing)?\b",
    "wildfire": r"\b(?:wildfires?|forest fires?)\b",
    "tsunami": r"\btsunamis?\b",
    "hurricane": r"\b(?:hurricanes?|cyclones?|typhoons?)\b",
    "tornado": r"\btornado(?:es)?\b",
    "volcano": r"\b(?:volcanic|volcano|eruption)\b",
}


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(_TIMESTAMP, value, re.IGNORECASE):
        raise dc.InvalidQuery("published_at must be an ISO 8601 timestamp with timezone")
    try:
        return datetime.fromisoformat(value.upper().replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        raise dc.InvalidQuery("published_at must be a valid timestamp") from None


def extract_report(snippet: str) -> dict:
    """Extract only what is written, retaining uncertain time as text."""
    types = [name for name, pattern in _TYPES.items() if re.search(pattern, snippet, re.IGNORECASE)]
    extracted = {"event_type": types[0] if len(types) == 1 else None,
                 "reported_location": None, "occurred_at": None,
                 "time_text": None, "magnitude": None}
    match = _REPORT.fullmatch(snippet)
    if not match or types != ["earthquake"]:
        return extracted
    place = match["place"].strip()
    # Only place-like names; conjunctions and extra clauses are not locations.
    if (not re.fullmatch(r"[^\W\d_][^\d\n]*", place)
            or re.search(r"\b(?:and|or|on|at|today|yesterday|not|no)\b", place, re.IGNORECASE)):
        return extracted
    extracted.update(reported_location=place, magnitude=float(match["magnitude"]),
                     time_text=match["time"] or match["relative"])
    if match["time"] and re.fullmatch(_TIMESTAMP, match["time"], re.IGNORECASE):
        try:
            extracted["occurred_at"] = dc._iso(_timestamp(match["time"]))
        except dc.InvalidQuery:
            pass
    return extracted


def _unresolved(extracted, reason, sources=None):
    return {"status": "unresolved", "reason": reason, "disaster_detected": None,
            "confidence": "unverified", "events": [],
            "sources_checked": sources or [], "extracted": extracted,
            "advisory": "This report is unresolved. This is not an all-clear for the location."}


def check_news(body: dict, now=None) -> dict:
    """Match one recent, precisely timed earthquake report to one USGS event."""
    snippet = body["news_snippet"]
    if not isinstance(snippet, str) or not snippet.strip() or len(snippet) > MAX_SNIPPET_LENGTH:
        raise dc.InvalidQuery("news_snippet must be a non-empty string of at most 2000 characters")
    if any(key in body for key in ("latitude", "longitude", "radius_km", "window_hours")):
        raise dc.InvalidQuery("news_snippet cannot be combined with coordinates, radius_km or window_hours")
    now = now or datetime.now(timezone.utc)
    published = _timestamp(body["published_at"]) if "published_at" in body else None
    if published and published > now:
        raise dc.InvalidQuery("published_at cannot be in the future")
    extracted = extract_report(snippet.strip())
    extracted["published_at"] = dc._iso(published) if published else None
    if extracted["event_type"] != "earthquake":
        return _unresolved(extracted, "unsupported_or_ambiguous_disaster_type")
    if not extracted["reported_location"]:
        return _unresolved(extracted, "missing_location_or_unsupported_wording")
    if not extracted["occurred_at"]:
        return _unresolved(extracted, "missing_or_ambiguous_occurrence_time")
    occurred = datetime.fromisoformat(extracted["occurred_at"].replace("Z", "+00:00"))
    if occurred > now or (published and occurred > published):
        return _unresolved(extracted, "inconsistent_occurrence_time")
    if occurred < now - timedelta(hours=dc.MAX_WINDOW_HOURS):
        return _unresolved(extracted, "outside_supported_time_window")
    if not usgs_earthquakes.MIN_MAGNITUDE <= extracted["magnitude"] <= 10:
        return _unresolved(extracted, "outside_supported_magnitude_range")
    point = disaster_geocoding.geocode_place(extracted["reported_location"])
    if point is None:
        return _unresolved(extracted, "unknown_or_ambiguous_location")
    extracted["coordinates"] = point
    # Query the existing adapter directly: impact-zone overlap alone cannot
    # confirm that a news report describes the same event. Do not ask other
    # event-type feeds or expand this radius by an earthquake's impact zone.
    try:
        found = usgs_earthquakes.fetch_events(
            point["latitude"], point["longitude"], MATCH_DISTANCE_KM, occurred - MATCH_TIME,
        )
        matches = [event for event in found if (
            event["event_type"] == "earthquake"
            and dc.distance_km(point["latitude"], point["longitude"],
                               event["latitude"], event["longitude"]) <= MATCH_DISTANCE_KM
            and abs(event["started_at"] - occurred) <= MATCH_TIME
            and event["started_at"] <= now < event["expires_at"]
            and abs(event["magnitude"] - extracted["magnitude"]) <= MAGNITUDE_TOLERANCE + 1e-9
        )]
    except Exception:
        raise dc.DisasterCheckUnavailable("USGS news matching unavailable") from None
    retrieved_at = dc._iso(now)
    sources = [{"source": "USGS", "event_types": ["earthquake"],
                "status": "ok", "retrieved_at": retrieved_at}]
    if len(matches) != 1:
        return _unresolved(extracted, "no_authoritative_match" if not matches
                           else "multiple_authoritative_matches", sources)
    event = matches[0]
    return {"status": "matched", "disaster_detected": True,
            "confidence": event["confidence"],
            "events": [dc._render(event, "USGS", retrieved_at)],
            "sources_checked": sources, "extracted": extracted}
