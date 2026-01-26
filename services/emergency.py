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
        "body": json.dumps(body)
    }

# ------------------ Data ------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "emergency_numbers.json")

_cache = None

def load_emergency_numbers():
    global _cache
    if _cache is None:
        with open(DATA_FILE, "r") as f:
            _cache = json.load(f)
    return _cache

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
    except:
        return {"country": "US"}


def reverse_geocode(lat, lng):
    """
    Uses OpenStreetMap (free, no key) to get city/state/country/zip
    """
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}"
        req = urllib.request.Request(url, headers={"User-Agent": "ngo-emergency-api"})
        with urllib.request.urlopen(req, timeout=4) as r:
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

def geocode_place(city=None, state=None, zip_code=None, country=None):
    """
    Forward geocode using OpenStreetMap
    """
    try:
        query_parts = [p for p in [zip_code, city, state, country] if p]
        query = ", ".join(query_parts)

        url = f"https://nominatim.openstreetmap.org/search?format=json&limit=1&q={query}"
        req = urllib.request.Request(url, headers={"User-Agent": "ngo-emergency-api"})
        with urllib.request.urlopen(req, timeout=4) as r:
            results = json.load(r)
            if not results:
                return None

            place = results[0]
            # reverse lookup for structured data
            return reverse_geocode(place["lat"], place["lon"])
    except:
        return None


def get_client_ip(event):
    """
    Supports:
    - API Gateway HTTP API (v2)
    - API Gateway REST API (v1)
    - ALB / CloudFront fallback
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


# ------------------ Resolver ------------------

def find_emergency_services(location, data, requested_service=None):
    zip_code = location.get("zip")
    city = location.get("city", "").title() if location.get("city") else None
    state = location.get("state", "").title() if location.get("state") else None
    country = location.get("country")

    if not country:
        return None, None

    country_data = data.get(country.upper(), {})

    def filter_service(services):
        if not services:
            return None
        if requested_service:
            return {requested_service: services.get(requested_service)} if services.get(requested_service) else None
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

    #  City
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

    #  State default
    if state:
        state_services = (
            country_data
            .get("states", {})
            .get(state, {})
            .get("default")
        )
        if state_services:
            return filter_service(state_services), "state"

    #  Country default
    if country_data.get("default"):
        return filter_service(country_data["default"]), "country"

    #  US fallback
    us_default = data.get("US", {}).get("default")
    return filter_service(us_default), "country"

def infer_state_country_from_city(city, data):
    """
    Search entire dataset to find which state & country a city belongs to.
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


# ------------------ Lambda ------------------

def lambda_handler(event, context):
    try:
        client_ip = get_client_ip(event)
        params = event.get("queryStringParameters") or {}

        service = params.get("service")
        lat = params.get("lat")
        lng = params.get("lng")
        zip_code = params.get("zip")
        city = params.get("city")
        state = params.get("state")
        country_override = params.get("country")

        location = {}

        # Load data early (needed for inference)
        data = load_emergency_numbers()

        # 1️⃣ GPS (strongest)
        if lat and lng:
            geo = reverse_geocode(lat, lng)
            if geo:
                location.update(geo)

        # 2️⃣ ZIP / CITY / STATE → geocode
        elif zip_code or city or state:
            geo = geocode_place(
                zip_code=zip_code,
                city=city,
                state=state,
                country=country_override
            )
            if geo:
                location.update(geo)

        # 3️⃣ City-based inference from DATA (no IP!)
        if city and not location.get("country"):
            inferred = infer_state_country_from_city(city, data)
            if inferred:
                location.update(inferred)

        # 4️⃣ Manual country override (testing only)
        if country_override:
            location["country"] = country_override.upper()

        # 5️⃣ IP fallback (LAST RESORT)
        if not location.get("country"):
            ip_loc = get_location_from_ip(client_ip)
            for k, v in ip_loc.items():
                if v:
                    location.setdefault(k, v)

        # 6️⃣ Resolve emergency services
        services, level = find_emergency_services(location, data, service)

        if not services:
            return response(404, {"error": "Emergency services not found"})

        return response(200, {
            "services": services,
            "match_level": level,
            "resolved_location": location,
            "client_ip": client_ip
        })

    except Exception as e:
        return response(500, {"error": str(e)})
