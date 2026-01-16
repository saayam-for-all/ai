import json
import os
import boto3
import urllib.request

s3 = boto3.client("s3")

BUCKET = os.environ["EMERGENCY_NUMBERS_BUCKET"]
KEY = os.environ["EMERGENCY_NUMBERS_KEY"]

_cache = None

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

def load_emergency_numbers():
    global _cache
    if _cache is None:
        obj = s3.get_object(Bucket=BUCKET, Key=KEY)
        _cache = json.loads(obj["Body"].read())
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



# ------------------ Lambda ------------------

def lambda_handler(event, context):
    try:
         
        client_ip = event["requestContext"]["http"]["sourceIp"]
        params = event.get("queryStringParameters") or {}
        service = params.get("service")
        lat = params.get("lat")
        lng = params.get("lng")
        zip_code = params.get("zip")
        country_override = params.get("country")

        location = {}

        # Allow manual country override (for testing)
        if country_override:
            location["country"] = country_override.upper()


        #  If GPS → strongest
        if lat and lng:
            geo = reverse_geocode(lat, lng)
            if geo:
                location = geo

        #  If no country yet → detect from IP
        if not location.get("country"):
            ip_loc = get_location_from_ip(client_ip)
            for k, v in ip_loc.items():
                if v:
                    location.setdefault(k, v)

        #  If ZIP provided → apply AFTER country is known
        if zip_code:
            location["zip"] = zip_code



        data = load_emergency_numbers()
        services, level = find_emergency_services(location, data, service)

        return response(200, {
            "services": services,
            "match_level": level,
            "resolved_location": location,
            "client_ip": client_ip
        })


    except Exception as e:
        return response(500, {"error": str(e)})
