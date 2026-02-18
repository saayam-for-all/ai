import json
from services.location_service import LocationService
from services.emergency_service import EmergencyService

# Instantiate services
location_service = LocationService()
emergency_service = EmergencyService()


# ------------------ Response Helper ------------------

def response(status, body):
    """Formats a Lambda-compatible HTTP response."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }


# ------------------ Lambda Handler ------------------

def lambda_handler(event, context):
    try:
        client_ip = location_service.get_client_ip(event)
        params = event.get("queryStringParameters") or {}

        service = params.get("service")
        lat = params.get("lat")
        lng = params.get("lng")
        zip_code = params.get("zip")
        city = params.get("city")
        state = params.get("state")
        country_override = params.get("country")

        location = {}

        # 1️⃣ GPS (strongest)
        if lat and lng:
            geo = location_service.reverse_geocode(lat, lng)
            if geo:
                location.update(geo)

        # 2️⃣ ZIP / CITY / STATE → geocode
        elif zip_code or city or state:
            geo = location_service.geocode_place(
                zip_code=zip_code,
                city=city,
                state=state,
                country=country_override
            )
            if geo:
                location.update(geo)

        # 3️⃣ City-based inference from dataset (no IP)
        if city and not location.get("country"):
            inferred = location_service.infer_state_country_from_city(
                city, 
                emergency_service.load_emergency_numbers()
            )
            if inferred:
                location.update(inferred)

        # 4️⃣ Manual country override (testing only)
        if country_override:
            location["country"] = country_override.upper()

        # 5️⃣ IP fallback (last resort)
        if not location.get("country"):
            ip_loc = location_service.get_location_from_ip(client_ip)
            for k, v in ip_loc.items():
                if v:
                    location.setdefault(k, v)

        # 6️⃣ Resolve emergency services
        services, level = emergency_service.find_emergency_services(location, service)

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