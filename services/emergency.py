import json
import os
import urllib.request


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, ensure_ascii=False)
    }


# ------------------ Data ------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "emergency_numbers.json")

_cache = None


def load_emergency_numbers():
    global _cache
    if _cache is None:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


# ------------------ i18n: Numeral Transliteration ------------------

# Mapping of language code to native numeral glyphs (positional, 0-9).
# Covers the 13 MVP languages. English uses ASCII digits (no mapping needed).
NUMERAL_MAP = {
    "hi": "०१२३४५६७८९",       # Hindi (Devanagari)
    "mr": "०१२३४५६७८९",       # Marathi (Devanagari)
    "ne": "०१२३४५६७८९",       # Nepali (Devanagari)
    "bn": "০১২৩৪৫৬৭৮৯",       # Bengali
    "ta": "௦௧௨௩௪௫௬௭௮௯",       # Tamil
    "te": "౦౧౨౩౪౫౬౭౮౯",       # Telugu
    "kn": "೦೧೨೩೪೫೬೭೮೯",       # Kannada
    "ml": "൦൧൨൩൪൫൬൭൮൯",       # Malayalam
    "gu": "૦૧૨૩૪૫૬૭૮૯",       # Gujarati
    "pa": "੦੧੨੩੪੫੬੭੮੯",       # Punjabi (Gurmukhi)
    "ar": "٠١٢٣٤٥٦٧٨٩",       # Arabic-Indic
    "ur": "۰۱۲۳۴۵۶۷۸۹",       # Extended Arabic-Indic (Urdu)
}

ASCII_DIGITS = "0123456789"

# Pre-build translation tables for performance (built once at cold start)
_TRANS_TABLES = {
    lang: str.maketrans(ASCII_DIGITS, numerals)
    for lang, numerals in NUMERAL_MAP.items()
}


def transliterate_number(number_str, language):
    """
    Convert ASCII digits in a string to the target language's numeral glyphs.
    Non-digit characters (spaces, "and", hyphens, etc.) are preserved as-is.

    Returns the original string if language is English or unsupported.
    """
    if not language or language == "en" or language not in _TRANS_TABLES:
        return number_str
    return number_str.translate(_TRANS_TABLES[language])


def localize_services(services, language):
    """
    Wrap each service with dial_number (ASCII, for tel: links)
    and display_number (localized script, for UI rendering).

    Input:  {"police": "911", "ambulance": "911"}
    Output: {"police": {"dial_number": "911", "display_number": "९११"}, ...}

    Frontend usage:
        <a href="tel:{dial_number}">{display_number}</a>
    """
    if not services:
        return services

    localized = {}
    for category, number in services.items():
        if isinstance(number, str):
            localized[category] = {
                "dial_number": number,
                "display_number": transliterate_number(number, language)
            }
        else:
            # Fallback for unexpected types
            localized[category] = number
    return localized


# ------------------ Geo helpers ------------------

def get_location_from_ip(ip):
    try:
        with urllib.request.urlopen(f"https://ipinfo.io/{ip}/json", timeout=3) as r:
            data = json.load(r)
            return {
                "zip": data.get("postal"),
                "city": data.get("city"),
                "state": data.get("region"),
                "country": data.get("country", "US")
            }
    except Exception:
        return {"country": "US"}


def reverse_geocode(lat, lng):
    """Uses OpenStreetMap (free, no key) to get city/state/country/zip."""
    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse"
            f"?format=json&lat={lat}&lon={lng}"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "saayam-emergency-api"}
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.load(r)
            addr = data.get("address", {})
            return {
                "zip": addr.get("postcode"),
                "city": (
                    addr.get("city")
                    or addr.get("town")
                    or addr.get("village")
                ),
                "state": addr.get("state"),
                "country": addr.get("country_code", "").upper()
            }
    except Exception:
        return None


def geocode_place(city=None, state=None, zip_code=None, country=None):
    """Forward geocode using OpenStreetMap."""
    try:
        query_parts = [p for p in [zip_code, city, state, country] if p]
        query = ", ".join(query_parts)

        url = (
            f"https://nominatim.openstreetmap.org/search"
            f"?format=json&limit=1&q={query}"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "saayam-emergency-api"}
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            results = json.load(r)
            if not results:
                return None

            place = results[0]
            return reverse_geocode(place["lat"], place["lon"])
    except Exception:
        return None


def get_client_ip(event):
    """
    Extract client IP. Supports:
    - API Gateway HTTP API (v2)
    - API Gateway REST API (v1)
    - ALB / CloudFront fallback
    """
    # HTTP API (v2)
    try:
        return event["requestContext"]["http"]["sourceIp"]
    except (KeyError, TypeError):
        pass

    # REST API (v1)
    try:
        return event["requestContext"]["identity"]["sourceIp"]
    except (KeyError, TypeError):
        pass

    # Header fallback
    headers = event.get("headers") or {}
    xff = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()

    return None


# ------------------ Resolver ------------------

def find_emergency_services(location, data, requested_service=None):
    zip_code = location.get("zip")
    city = (location.get("city", "").title()
            if location.get("city") else None)
    state = (location.get("state", "").title()
             if location.get("state") else None)
    country = location.get("country")

    if not country:
        return None, None

    country_data = data.get(country.upper(), {})

    def filter_service(services):
        if not services:
            return None
        if requested_service:
            val = services.get(requested_service)
            return {requested_service: val} if val else None
        return services

    # ZIP
    if zip_code:
        zip_services = (
            country_data
            .get("states", {})
            .get(state, {})
            .get("zips", {})
            .get(zip_code)
        )
        if zip_services:
            return filter_service(zip_services), "zip"

    # City
    if city:
        city_services = (
            country_data
            .get("states", {})
            .get(state, {})
            .get("cities", {})
            .get(city)
        )
        if city_services:
            return filter_service(city_services), "city"

    # State default
    if state:
        state_services = (
            country_data
            .get("states", {})
            .get(state, {})
            .get("default")
        )
        if state_services:
            return filter_service(state_services), "state"

    # Country default
    if country_data.get("default"):
        return filter_service(country_data["default"]), "country"

    # US fallback
    us_default = data.get("US", {}).get("default")
    return filter_service(us_default), "country"


def infer_state_country_from_city(city, data):
    """Search entire dataset to find which state & country a city belongs to."""
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


# ------------------ Classes ------------------


def _parse_params(event):
    """Extract params from query string and/or JSON body."""
    params = dict(event.get("queryStringParameters") or {})
    body = event.get("body")
    if body and str(body).strip():
        try:
            params.update(json.loads(body))
        except (json.JSONDecodeError, TypeError):
            pass
    return params


class LocationResolver:
    """Resolves location from GPS, geocoding, city inference, or IP fallback."""

    def __init__(self, client_ip):
        self.client_ip = client_ip

    def resolve(self, params, data):
        location = {}
        lat = params.get("lat")
        lng = params.get("lng")
        zip_code = params.get("zip")
        city = params.get("city")
        state = params.get("state")
        country_override = params.get("country")

        if lat and lng:
            geo = reverse_geocode(lat, lng)
            if geo:
                location.update(geo)
        elif zip_code or city or state:
            geo = geocode_place(
                zip_code=zip_code, city=city,
                state=state, country=country_override
            )
            if geo:
                location.update(geo)

        if city and not location.get("country"):
            inferred = infer_state_country_from_city(city, data)
            if inferred:
                location.update(inferred)

        if country_override:
            location["country"] = country_override.upper()

        if not location.get("country") and self.client_ip:
            ip_loc = get_location_from_ip(self.client_ip)
            for k, v in ip_loc.items():
                if v:
                    location.setdefault(k, v)

        return location


class EmergencyServiceResolver:
    """Loads emergency data and resolves services by location."""

    def load_data(self):
        return load_emergency_numbers()

    def find_services(self, location, requested_service=None):
        return find_emergency_services(
            location, self.load_data(), requested_service
        )


# ------------------ Lambda ------------------


def lambda_handler(event, context):
    try:
        client_ip = get_client_ip(event)
        params = _parse_params(event)

        service_resolver = EmergencyServiceResolver()
        data = service_resolver.load_data()

        location_resolver = LocationResolver(client_ip)
        location = location_resolver.resolve(params, data)

        services, level = service_resolver.find_services(
            location, params.get("service")
        )

        if not services:
            return response(404, {"error": "Emergency services not found"})

        language = params.get("language", "en")
        localized = localize_services(services, language)

        return response(200, {
            "services": localized,
            "language": language,
            "match_level": level,
            "resolved_location": location,
            "client_ip": client_ip
        })

    except Exception as e:
        return response(500, {"error": str(e)})