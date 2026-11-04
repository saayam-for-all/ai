"""Bounded forward geocoding for news queries; never choose the first match.

Uses the hosted maps.co Nominatim API, not OSM's rate-limited public server.
Only the extracted place is sent. Credentials stay in SSM and HTTP headers.
"""
import http.client
import json
import math
import os
import urllib.parse
import urllib.request
from functools import lru_cache

from services.disaster_check import DisasterCheckUnavailable

SEARCH_URL = "https://geocode.maps.co/search"
TIMEOUT_SECONDS = 4
DEFAULT_KEY_PARAMETER = "/dev/saayam/GenAI/geocoding/key"


@lru_cache(maxsize=1)
def _api_key():
    # Lazy loading keeps SSM and credentials off the coordinate/import path.
    import boto3
    from botocore.config import Config

    try:
        client = boto3.client("ssm", config=Config(
            connect_timeout=2, read_timeout=2, retries={"total_max_attempts": 1},
        ))
        key = client.get_parameter(
            Name=os.environ.get("DISASTER_GEOCODING_KEY_PARAMETER", DEFAULT_KEY_PARAMETER),
            WithDecryption=True,
        )["Parameter"]["Value"]
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Missing key")
        return key
    except Exception:
        raise DisasterCheckUnavailable("Geocoding credentials unavailable") from None


def geocode_place(place: str) -> dict | None:
    """Return a unique point, or None for unknown/ambiguous places.

    Rate limits (429), timeouts and malformed data are outages, never unknown
    places. No retries: callers must back off rather than amplify throttling.
    """
    query = urllib.parse.urlencode({"q": place, "format": "json", "limit": 2})
    request = urllib.request.Request(
        f"{SEARCH_URL}?{query}",
        headers={"Authorization": f"Bearer {_api_key()}",
                 "User-Agent": "saayam-disaster-check"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310
            results = json.load(response)
        if not isinstance(results, list):
            raise ValueError("Expected a geocoding result list")
        points = []
        for result in results:
            lat, lon = result["lat"], result["lon"]
            if isinstance(lat, bool) or isinstance(lon, bool):
                raise ValueError("Boolean coordinate")
            lat, lon = float(lat), float(lon)
            if not (math.isfinite(lat) and -90 <= lat <= 90
                    and math.isfinite(lon) and -180 <= lon <= 180):
                raise ValueError("Invalid coordinate")
            points.append({"latitude": lat, "longitude": lon})
    except (OSError, ValueError, TypeError, KeyError, OverflowError, http.client.HTTPException):
        # Exception strings can contain request URLs or credentials.
        raise DisasterCheckUnavailable("Geocoding unavailable") from None
    return points[0] if len(points) == 1 else None
