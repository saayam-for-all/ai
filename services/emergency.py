"""Emergency contacts resolution.

Two rules govern everything in this module, both from issue #146:

1. A number shown to a user must belong to the country that user is in. There
   is no cross-border fallback anywhere in this file. If we cannot resolve a
   country the answer is "unavailable", never another country's number.
2. A missing service must not leave the field empty, because the web client
   fills empty fields with hardcoded US numbers (911 / 988). When a specific
   service is missing for a country we return that country's own general
   emergency line, flagged as a fallback rather than passed off as the real
   thing.
"""
import ipaddress
import json
import os
import urllib.parse
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


# -------------------------------------------------------------------------
# Service vocabulary
# -------------------------------------------------------------------------

GENERAL_EMERGENCY = "general_emergency"

# The services this API answers for. A request for anything outside this set is
# answered "unavailable" rather than with a general emergency number: somebody
# asking for a service we do not model must not be handed 112 as if it were one.
KNOWN_SERVICES = (
    GENERAL_EMERGENCY,
    "police",
    "ambulance",
    "fire",
    "disaster_management",
    "women_helpline",
    "suicide_helpline",
)

# How a returned number was arrived at. The client can label a fallback
# differently ("general emergency line") instead of presenting it as, say, a
# dedicated women's helpline.
SOURCE_DIRECTORY = "directory"
SOURCE_GENERAL_FALLBACK = "general_emergency_fallback"

# Characters a phone number may contain. Anything else - a range, a note such
# as "115 and 1122", an empty string - is not dialable and is dropped rather
# than rendered into a click-to-call link that cannot connect.
_DIALABLE_CHARS = set("0123456789+-().# ")


def is_dialable(number):
    """True if number is something a handset could actually dial."""
    if not isinstance(number, str):
        return False
    text = number.strip()
    if not 2 <= len(text) <= 20:
        return False
    if not set(text) <= _DIALABLE_CHARS:
        return False
    return any(ch.isdigit() for ch in text)


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
        """Turn resolved entries into the wire shape the web client reads.

        Input is what the resolver produces: {service: {"number", "source"}}.
        Output keeps dial_number and display_number, which the client already
        depends on, and adds the provenance fields alongside them.
        """
        if not services:
            return services
        localized = {}
        for category, entry in services.items():
            number = entry["number"]
            localized[category] = {
                "dial_number": number,
                "display_number": self.transliterate_number(number, language),
                "source": entry["source"],
                "is_fallback": entry["source"] != SOURCE_DIRECTORY,
            }
        return localized


class LocationResolver:
    def __init__(self, client_ip):
        self.client_ip = client_ip

    def _get_location_from_ip(self, ip):
        # The IP arrives from a request header and is interpolated into a URL,
        # so it is parsed as an address first: an unvalidated value could
        # rewrite the path and point the lookup somewhere else entirely.
        try:
            ipaddress.ip_address(str(ip).strip())
        except ValueError:
            return {}
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
        # lat/lng come straight off the query string. Coercing to float both
        # validates them and stops arbitrary text being interpolated into the URL.
        try:
            lat = float(lat)
            lng = float(lng)
        except (TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None
        try:
            query = urllib.parse.urlencode({"format": "json", "lat": lat, "lon": lng})
            req = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/reverse?{query}",
                headers={"User-Agent": "saayam-emergency-api"},
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
        # Place names are user text, so they are percent-encoded rather than
        # pasted into the URL: a name containing & or # would otherwise
        # silently change the request.
        parts = [str(p).strip() for p in (zip_code, city, state, country) if p]
        if not parts:
            return None
        try:
            query = urllib.parse.urlencode(
                {"format": "json", "limit": 1, "q": ", ".join(parts)}
            )
            req = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/search?{query}",
                headers={"User-Agent": "saayam-emergency-api"},
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
        """Locate a bare city name in the directory.

        Accepted only when exactly one country contains that city. City names
        repeat across borders, and guessing wrong here is precisely the
        cross-jurisdiction failure this module exists to prevent.
        """
        if not city:
            return None
        city_norm = city.title()
        matches = []
        for country_code, country_data in data.items():
            for state_name, state_data in country_data.get("states", {}).items():
                if city_norm in state_data.get("cities", {}):
                    matches.append({
                        "city": city_norm,
                        "state": state_name,
                        "country": country_code,
                    })
        if len(matches) != 1:
            return None
        return matches[0]

    def resolve(self, params, data):
        location = {}
        lat = params.get("lat")
        lng = params.get("lng")
        zip_code = params.get("zip")
        city = params.get("city")
        state = params.get("state")
        country_override = _normalize_country(params.get("country"))

        if lat and lng:
            geo = self._reverse_geocode(lat, lng)
            if geo:
                location.update(geo)
        elif zip_code or city or state:
            geo = self._geocode_place(
                zip_code=zip_code, city=city,
                state=state, country=params.get("country")
            )
            if geo:
                location.update(geo)

        if city and not location.get("country"):
            inferred = self._infer_state_country_from_city(city, data)
            if inferred:
                location.update(inferred)

        if country_override:
            # An explicit country wins. The finer-grained fields resolved from
            # somewhere else are then discarded: a state or city belonging to a
            # different country would otherwise be looked up inside this one and
            # match by coincidence.
            if location.get("country") and location["country"] != country_override:
                location = {}
            location["country"] = country_override

        if not location.get("country") and self.client_ip:
            ip_loc = self._get_location_from_ip(self.client_ip)
            for k, v in ip_loc.items():
                if v:
                    location.setdefault(k, v)

        return location


class EmergencyServiceResolver:
    def _load_data(self):
        return _load_emergency_numbers()

    @staticmethod
    def _general_emergency_number(country_data):
        """This country's own pan-emergency line.

        The explicit general_emergency entry when the dataset has one,
        otherwise the country's police line, which for most countries here is
        the national single number (112 in India and the EU, 999 in the UK, 911
        in the US). Reads one country's record and never another's.
        """
        default = country_data.get("default") or {}
        for key in (GENERAL_EMERGENCY, "police"):
            number = default.get(key)
            if is_dialable(number):
                return number.strip()
        return None

    def _find_services(self, location, data, requested_service=None):
        """Resolve services for a location.

        Returns ({service: {"number", "source"}}, match_level), or (None, None)
        when nothing can be resolved inside the country. Every lookup below is
        scoped to country_data, so no path can reach another country's record.
        """
        zip_code = location.get("zip")
        city = (location.get("city", "").title() if location.get("city") else None)
        state = (location.get("state", "").title() if location.get("state") else None)
        country = _normalize_country(location.get("country"))

        if not country:
            return None, None

        country_data = data.get(country) or {}
        if not country_data:
            # Unknown / unmatched country (e.g. locale sent as a name instead of an
            # ISO code): do NOT cross jurisdictions. Report unavailable rather than
            # returning another country's emergency numbers.
            return None, None

        state_data = (
            country_data.get("states", {}).get(state, {}) if state else {}
        )

        # Levels within this country, broadest first. Anything more specific
        # overrides what came before it, so a city entry listing only police and
        # ambulance still inherits fire from its state or country default
        # instead of leaving that field empty.
        levels = [
            (country_data.get("default"), "country"),
            (state_data.get("default") if state else None, "state"),
            (state_data.get("cities", {}).get(city) if city else None, "city"),
            (state_data.get("zips", {}).get(zip_code) if zip_code else None, "zip"),
        ]

        merged = {}
        match_level = None
        for services, level in levels:
            if not services:
                continue
            match_level = level          # ends on the most specific level present
            for name, number in services.items():
                if is_dialable(number):
                    # `level` is kept per service so a single-service request can
                    # report where that number actually came from: asking for fire
                    # from a city that does not list one is a country-level answer
                    # even though the location matched at city level.
                    merged[name] = {
                        "number": number.strip(),
                        "source": SOURCE_DIRECTORY,
                        "level": level,
                    }

        general = self._general_emergency_number(country_data)

        if requested_service:
            if requested_service in merged:
                entry = merged[requested_service]
                return {requested_service: entry}, entry["level"]
            # Not in the directory for this country. Fall back to this country's
            # own general line - but only for services we actually model, so an
            # unrecognised service name cannot be answered with 112.
            if requested_service in KNOWN_SERVICES and general:
                return (
                    {requested_service: {
                        "number": general,
                        "source": SOURCE_GENERAL_FALLBACK,
                        "level": "country",
                    }},
                    "country",
                )
            return None, None

        if not merged:
            return None, None

        # Fill the services we model but have no entry for, so the client is
        # never handed a gap to paper over with a US default.
        if general:
            for name in KNOWN_SERVICES:
                merged.setdefault(name, {
                    "number": general,
                    "source": SOURCE_GENERAL_FALLBACK,
                    "level": "country",
                })

        return merged, match_level

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

        language = params.get("language") or "en"
        localization = LocalizationService()
        localized = localization.localize_services(services, language)

        return {
            "status": 200,
            "body": {
                "services": localized,
                "language": language,
                "country": _normalize_country(location.get("country")),
                "match_level": level,
                "resolved_location": location,
                "client_ip": client_ip
            }
        }
    except Exception as e:
        return {"status": 500, "body": {"error": str(e)}}
