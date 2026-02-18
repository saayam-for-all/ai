import json
import urllib.request
from config import NOMINATIM_USER_AGENT, GEOCODE_TIMEOUT, IPINFO_TIMEOUT, IPINFO_URL, DEFAULT_COUNTRY


class LocationService:
    """Handles all location resolution — GPS, IP, ZIP, city, and dataset inference."""

    # ------------------ IP & Event Helpers ------------------

    @staticmethod
    def get_client_ip(event):
        """
        Extracts client IP from Lambda event. Supports:
        - API Gateway HTTP API (v2)
        - API Gateway REST API (v1)
        - ALB / CloudFront header fallback
        """
        # HTTP API (v2)
        try:
            return event["requestContext"]["http"]["sourceIp"]
        except:
            pass

        # REST API (v1)
        try:
            return event["requestContext"]["identity"]["sourceIp"]
        except:
            pass

        # Header fallback
        headers = event.get("headers") or {}
        xff = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()

        return None

    @staticmethod
    def get_location_from_ip(ip):
        """Resolves location from IP address using ipinfo.io. Falls back to DEFAULT_COUNTRY."""
        try:
            with urllib.request.urlopen(f"{IPINFO_URL}/{ip}/json", timeout=IPINFO_TIMEOUT) as r:
                data = json.load(r)
                return {
                    "zip": data.get("postal"),
                    "city": data.get("city"),
                    "state": data.get("region"),
                    "country": data.get("country", DEFAULT_COUNTRY)
                }
        except:
            return {"country": DEFAULT_COUNTRY}

    # ------------------ Geocoding ------------------

    @staticmethod
    def reverse_geocode(lat, lng):
        """Converts GPS coordinates to city/state/country/zip using OpenStreetMap (no API key needed)."""
        try:
            url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}"
            req = urllib.request.Request(url, headers={"User-Agent": NOMINATIM_USER_AGENT})
            with urllib.request.urlopen(req, timeout=GEOCODE_TIMEOUT) as r:
                data = json.load(r)
                addr = data.get("address", {})
                return {
                    "zip": addr.get("postcode"),
                    "city": addr.get("city") or addr.get("town") or addr.get("village"),
                    "state": addr.get("state"),
                    "country": addr.get("country_code", "").upper()
                }
        except:
            return None

    @staticmethod
    def geocode_place(city=None, state=None, zip_code=None, country=None):
        """Forward geocodes a city/state/zip into structured location data using OpenStreetMap."""
        try:
            query_parts = [p for p in [zip_code, city, state, country] if p]
            query = ", ".join(query_parts)

            url = f"https://nominatim.openstreetmap.org/search?format=json&limit=1&q={query}"
            req = urllib.request.Request(url, headers={"User-Agent": NOMINATIM_USER_AGENT})
            with urllib.request.urlopen(req, timeout=GEOCODE_TIMEOUT) as r:
                results = json.load(r)
                if not results:
                    return None

                place = results[0]
                # Reverse lookup to get full structured address
                return LocationService.reverse_geocode(place["lat"], place["lon"])
        except:
            return None

    # ------------------ Dataset Inference ------------------

    @staticmethod
    def infer_state_country_from_city(city, data):
        """
        Searches the emergency dataset to infer state & country from a city name alone.
        Used when no geocoding result is available.
        """
        if not city:
            return None

        city_norm = city.title()

        for country_code, country_data in data.items():
            states = country_data.get("states", {})
            for state_name, state_data in states.items():
                cities = state_data.get("cities", {})
                if city_norm in cities:
                    return {
                        "city": city_norm,
                        "state": state_name,
                        "country": country_code
                    }

        return None