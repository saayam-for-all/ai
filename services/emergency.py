import json
import os
import urllib.request


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "emergency_numbers.json")

# Module-level cache: reused across Lambda invocations in the same warm container (same as pre-refactor).
_emergency_numbers_cache = None


def _load_emergency_numbers():
    global _emergency_numbers_cache
    if _emergency_numbers_cache is None:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            _emergency_numbers_cache = json.load(f)
    return _emergency_numbers_cache


# Best-effort aliases for callers that send a country NAME instead of an ISO-3166
# alpha-2 code (the dataset is keyed by alpha-2). Extend as needed. Anything not
# matched here stays as-is and, if it isn't a real code, resolves to "unavailable"
# - it never falls back to another country's numbers.
_COUNTRY_ALIASES = {
    "usa": "US", "united states": "US", "united states of america": "US",
    "america": "US", "u.s.": "US", "u.s.a.": "US",
    "india": "IN", "bharat": "IN",
    "uk": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "uae": "AE", "united arab emirates": "AE",
}


def _normalize_country(country):
    """Normalize a country value to an ISO-3166 alpha-2 code, best-effort."""
    if not country:
        return None
    c = str(country).strip()
    if len(c) == 2:                       # already an alpha-2 code (e.g. "IN", "us")
        return c.upper()
    return _COUNTRY_ALIASES.get(c.lower(), c.upper())


NUMERAL_MAP = {
    "hi": "०१२३४५६७८९",
    "mr": "०१२३४५६७८९",
    "ne": "०१२३४५६७८९",
    "bn": "০১২৩৪৫৬৭৮৯",
    "ta": "௦௧௨௩௪௫௬௭௮௯",
    "te": "౦౧౨౩౪౫౬౭౮౯",
    "kn": "೦೧೨೩೪೫೬೭೮೯",
    "ml": "൦൧൨൩൪൫൬൭൮൯",
    "gu": "૦૧૨૩૪૫૬૭૮૯",
    "pa": "੦੧੨੩੪੫੬੭੮੯",
    "ar": "٠١٢٣٤٥٦٧٨٩",
    "ur": "۰۱۲۳۴۵۶۷۸۹",
}
ASCII_DIGITS = "0123456789"
_TRANS_TABLES = {
    lang: str.maketrans(ASCII_DIGITS, numerals)
    for lang, numerals in NUMERAL_MAP.items()
}


class LocalizationService:
    def transliterate_number(self, number_str, language):
        if not language or language == "en" or language not in _TRANS_TABLES:
            return number_str
        return number_str.translate(_TRANS_TABLES[language])

    def localize_services(self, services, language):
        if not services:
            return services
        localized = {}
        for category, number in services.items():
            if isinstance(number, str):
                localized[category] = {
                    "dial_number": number,
                    "display_number": self.transliterate_number(number, language)
                }
            else:
                localized[category] = number
        return localized


class LocationResolver:
    def __init__(self, client_ip):
        self.client_ip = client_ip

    def _get_location_from_ip(self, ip):
        try:
            with urllib.request.urlopen(f"https://ipinfo.io/{ip}/json", timeout=3) as r:
                data = json.load(r)
                return {
                    "zip": data.get("postal"),
                    "city": data.get("city"),
                    "state": data.get("region"),
                    # Do NOT assume US when the country is unknown - an unresolved
                    # country must not silently inherit US emergency numbers.
                    "country": data.get("country")
                }
        except Exception:
            return {}

    def _reverse_geocode(self, lat, lng):
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

    def _geocode_place(self, zip_code=None, city=None, state=None, country=None):
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
                return self._reverse_geocode(place["lat"], place["lon"])
        except Exception:
            return None

    def _infer_state_country_from_city(self, city, data):
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

    def resolve(self, params, data):
        location = {}
        lat = params.get("lat")
        lng = params.get("lng")
        zip_code = params.get("zip")
        city = params.get("city")
        state = params.get("state")
        country_override = params.get("country")

        if lat and lng:
            geo = self._reverse_geocode(lat, lng)
            if geo:
                location.update(geo)
        elif zip_code or city or state:
            geo = self._geocode_place(
                zip_code=zip_code, city=city,
                state=state, country=country_override
            )
            if geo:
                location.update(geo)

        if city and not location.get("country"):
            inferred = self._infer_state_country_from_city(city, data)
            if inferred:
                location.update(inferred)

        if country_override:
            location["country"] = country_override.upper()

        if not location.get("country"):
            ip_loc = self._get_location_from_ip(self.client_ip)
            for k, v in ip_loc.items():
                if v:
                    location.setdefault(k, v)

        return location


class EmergencyServiceResolver:
    def _load_data(self):
        return _load_emergency_numbers()

    def _find_services(self, location, data, requested_service=None):
        zip_code = location.get("zip")
        city = (location.get("city", "").title() if location.get("city") else None)
        state = (location.get("state", "").title() if location.get("state") else None)
        country = _normalize_country(location.get("country"))

        if not country:
            return None, None

        country_data = data.get(country, {})
        if not country_data:
            # Unknown / unmatched country (e.g. locale sent as a name instead of an
            # ISO code): do NOT cross jurisdictions. Report unavailable rather than
            # returning another country's emergency numbers.
            return None, None

        state_data = (
            country_data.get("states", {}).get(state, {}) if state else {}
        )

        # Candidate service sets, most specific first - ALL within the resolved
        # country. We never fall back to another country (e.g. US).
        candidates = [
            (state_data.get("zips", {}).get(zip_code) if zip_code else None, "zip"),
            (state_data.get("cities", {}).get(city) if city else None, "city"),
            (state_data.get("default") if state else None, "state"),
            (country_data.get("default"), "country"),
        ]

        if requested_service:
            # Return the first level that actually has this service (within-country
            # descent: zip -> city -> state -> country default). If no level in this
            # country provides it, return None ("unavailable") - never a foreign number.
            for services, level in candidates:
                if services and services.get(requested_service):
                    return {requested_service: services[requested_service]}, level
            return None, None

        # No specific service requested: return the most specific full set available
        # within this country.
        for services, level in candidates:
            if services:
                return services, level
        return None, None

    def load_data(self):
        return self._load_data()

    def find_services(self, location, requested_service=None):
        return self._find_services(
            location, self.load_data(), requested_service
        )


def get_emergency_services(params, client_ip):
    try:
        service_resolver = EmergencyServiceResolver()
        data = service_resolver.load_data()

        location_resolver = LocationResolver(client_ip)
        location = location_resolver.resolve(params, data)

        services, level = service_resolver.find_services(
            location, params.get("service")
        )

        if not services:
            return {"status": 404, "body": {"error": "Emergency services not found"}}

        language = params.get("language", "en")
        localization = LocalizationService()
        localized = localization.localize_services(services, language)

        return {
            "status": 200,
            "body": {
                "services": localized,
                "language": language,
                "match_level": level,
                "resolved_location": location,
                "client_ip": client_ip
            }
        }
    except Exception as e:
        return {"status": 500, "body": {"error": str(e)}}

