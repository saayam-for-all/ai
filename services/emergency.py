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
import hashlib
import ipaddress
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


S3_BUCKET = os.environ.get("EMERGENCY_CONTACTS_S3_BUCKET", "saayam-virginia-public")
S3_KEY = os.environ.get("EMERGENCY_CONTACTS_S3_KEY", "emergency_contact.json")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "emergency_numbers.json")

# Module-level cache: reused across Lambda invocations in the same warm container.
_emergency_numbers_cache = None

logger = logging.getLogger(__name__)


def _log_level(name):
    """Level named by EMERGENCY_LOG_LEVEL, INFO by default.

    A typo in the variable must not stop the module importing, so anything that
    is not a level name falls back to INFO.
    """
    level = logging.getLevelName(str(name or "INFO").strip().upper())
    return level if isinstance(level, int) else logging.INFO


# The Lambda runtime leaves the root logger at WARNING. Without a level on this
# logger the INFO lines below - one per request, the lines that explain why a
# user saw the numbers they saw - would never reach CloudWatch.
logger.setLevel(_log_level(os.environ.get("EMERGENCY_LOG_LEVEL")))


def _mask_ip(ip):
    """An IP with the host part removed, for logs.

    Enough to see which network and country a lookup was made for, not enough
    to identify the person: 74.102.193.3 becomes 74.102.193.x.
    """
    if not ip:
        return "none"
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return "invalid"
    if addr.version == 4:
        return str(addr).rsplit(".", 1)[0] + ".x"
    return str(ipaddress.ip_network(f"{addr}/48", strict=False).network_address) + "/48"


def _coarse(value):
    """A coordinate rounded to one decimal (about 11 km), or None.

    Enough to tell Prague from Houston in a log, not enough to locate a person.
    """
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _describe(location):
    """'city, state, country' from whichever of those a location has."""
    parts = [location.get(k) for k in ("city", "state", "country")] if location else []
    return ", ".join(str(p) for p in parts if p) or "unknown"


def _lookup_failure_reason(error):
    """Why a call to ipinfo or Nominatim failed, in a few words.

    These lookups used to fail silently, which left the logs unable to say
    whether a wrong country came from a timeout, a rate limit or a refusal.
    """
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 429:
            return "HTTP 429 (rate limited)"
        return f"HTTP {error.code}"
    if isinstance(error, urllib.error.URLError):
        reason = error.reason
        if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason).lower():
            return "timeout"
        return f"network error ({type(reason).__name__}: {reason})"
    if isinstance(error, (socket.timeout, TimeoutError)) or "timed out" in str(error).lower():
        return "timeout"
    if isinstance(error, json.JSONDecodeError):
        return "response was not JSON"
    return f"{type(error).__name__}: {error}"


def _elapsed_ms(started):
    return int((time.monotonic() - started) * 1000)

# S3 is read inside the first request a container serves, and the function's
# timeout is 3 s. One attempt only: botocore's legacy `max_attempts` counts
# retries rather than attempts, so `max_attempts: 1` made two, and two 1.5 s
# connect timeouts outlasted the function before the fallback could answer.
# With these settings an unreachable S3 costs about a second.
_S3_CLIENT_OPTIONS = {
    "connect_timeout": 1,
    "read_timeout": 1,
    "retries": {"total_max_attempts": 1, "mode": "standard"},
}


def _validate_dataset(data):
    """Return data if it is shaped like the directory, else raise ValueError.

    Parsing proves only that the bytes are JSON. `[]` and `{}` parse too, and
    once cached they would answer every request in the container with a 500
    or a 404 until it recycled. A dataset that fails here is treated exactly
    like one that could not be read.
    """
    if not isinstance(data, dict) or not data:
        raise ValueError(
            f"expected a non-empty object keyed by country, got {type(data).__name__} "
            f"of length {len(data) if hasattr(data, '__len__') else 'n/a'}"
        )
    for code, record in data.items():
        if not (isinstance(code, str) and len(code) == 2 and code.isalpha() and code.isupper()):
            raise ValueError(f"country key {code!r} is not an ISO-3166 alpha-2 code")
        if not (
            isinstance(record, dict)
            and isinstance(record.get("default", {}), dict)
            and isinstance(record.get("states", {}), dict)
        ):
            raise ValueError(f"country {code} is not a {{default, states}} object")
    return data


def _log_loaded(source, raw, data):
    """One line per cold start naming where the directory came from.

    The bundled file is a byte-identical copy of the S3 object, so the numbers
    alone cannot say which one answered. The SHA-256 ties the running data to
    a specific upload.
    """
    print(
        f"INFO: Loaded emergency numbers from {source} "
        f"({len(data)} countries, sha256={hashlib.sha256(raw).hexdigest()})"
    )


def _read_bundled():
    """(raw bytes, directory) of the copy packaged with the code, or (None, None)."""
    if not os.path.exists(DATA_FILE):
        return None, None
    with open(DATA_FILE, "rb") as f:
        raw = f.read()
    return raw, _validate_dataset(json.loads(raw.decode("utf-8")))


def _check_covers_bundled(data, bundled):
    """Raise ValueError if data drops a country the bundled copy can answer for.

    The shape check passes a file that is well formed but incomplete: a
    partial export with one country, or records whose numbers are empty or
    prose. Cached, such a file turns every missing country into a 404 for the
    life of the container, while the bundled copy that could answer is never
    read. So every country with a dialable general or police number in the
    bundled copy must still have one here.

    This also means S3 cannot drop a country's number on its own: the bundled
    copy has to change in the same release, which it must anyway, since
    test_bundled_file_is_the_s3_ground_truth pins it to the S3 object.
    """
    general = EmergencyServiceResolver._general_emergency_number
    lost = sorted(
        code for code, record in bundled.items()
        if general(record) and not general(data.get(code) or {})
    )
    if lost:
        shown = ", ".join(lost[:10]) + (", ..." if len(lost) > 10 else "")
        raise ValueError(
            f"no dialable general or police number for {len(lost)} "
            f"countries the bundled copy covers: {shown}"
        )


def _load_emergency_numbers():
    global _emergency_numbers_cache
    if _emergency_numbers_cache is not None:
        return _emergency_numbers_cache

    # Attempt to load from S3 if configured
    if S3_BUCKET and S3_KEY:
        try:
            import boto3
            from botocore.config import Config

            s3_client = boto3.client(
                "s3",
                region_name=AWS_REGION,
                config=Config(**_S3_CLIENT_OPTIONS),
            )
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
            raw = response["Body"].read()
            data = _validate_dataset(json.loads(raw.decode("utf-8")))

            bundled_raw, bundled = _read_bundled()
            if bundled is not None:
                _check_covers_bundled(data, bundled)
                if raw != bundled_raw:
                    # S3 is the ground truth, so it still answers. But the
                    # bundled copy is what a container serves when S3 cannot
                    # be read, and it now says something different. One line
                    # a CloudWatch metric filter can alert on.
                    print(
                        f"WARN: Emergency numbers in s3://{S3_BUCKET}/{S3_KEY} differ from "
                        f"the bundled file (s3 sha256={hashlib.sha256(raw).hexdigest()}, "
                        f"bundled sha256={hashlib.sha256(bundled_raw).hexdigest()}). "
                        "A fallback would serve different numbers: update "
                        "services/emergency_numbers.json to match S3."
                    )

            _emergency_numbers_cache = data
            _log_loaded(f"s3://{S3_BUCKET}/{S3_KEY}", raw, data)
            return _emergency_numbers_cache
        except Exception as e:
            # Fall back to local bundled JSON on any S3 error (IAM deny, missing key,
            # network, malformed, misshapen or incomplete object, local dev)
            print(f"WARN: Could not fetch emergency numbers from s3://{S3_BUCKET}/{S3_KEY} ({type(e).__name__}: {e}). Falling back to local file.")

    raw, bundled = _read_bundled()
    if bundled is not None:
        _emergency_numbers_cache = bundled
        _log_loaded("the bundled file", raw, bundled)
        return _emergency_numbers_cache

    raise RuntimeError("Emergency numbers dataset is not available from S3 or local package.")


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
    "child_helpline",
    "coastguard",
    "traffic_police",
    "gendarmerie",
    "gas_leak",
    "general_emergency_alternate",
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
        # How the last resolve() found the country: gps, place, city_directory,
        # country_param, ip or none. Logged rather than returned, so the
        # response the web client reads keeps its shape.
        self.source = "none"

    def _get_location_from_ip(self, ip):
        # The IP arrives from a request header and is interpolated into a URL,
        # so it is parsed as an address first: an unvalidated value could
        # rewrite the path and point the lookup somewhere else entirely.
        try:
            ipaddress.ip_address(str(ip).strip())
        except ValueError:
            logger.warning("ipinfo lookup skipped: client IP is not a valid address (%s)", _mask_ip(ip))
            return {}
        started = time.monotonic()
        try:
            with urllib.request.urlopen(f"https://ipinfo.io/{ip}/json", timeout=3) as r:
                data = json.load(r)
                location = {
                    "zip": data.get("postal"),
                    "city": data.get("city"),
                    "state": data.get("region"),
                    # Do NOT assume US when the country is unknown - an unresolved
                    # country must not silently inherit US emergency numbers.
                    "country": data.get("country")
                }
        except Exception as e:
            logger.warning(
                "ipinfo lookup failed for ip=%s: %s (%d ms)",
                _mask_ip(ip), _lookup_failure_reason(e), _elapsed_ms(started),
            )
            return {}
        if location["country"]:
            logger.info(
                "ipinfo lookup: ip=%s -> %s (%d ms)",
                _mask_ip(ip), _describe(location), _elapsed_ms(started),
            )
        else:
            logger.warning(
                "ipinfo lookup for ip=%s returned no country (%d ms)",
                _mask_ip(ip), _elapsed_ms(started),
            )
        return location

    def _reverse_geocode(self, lat, lng):
        # lat/lng come straight off the query string. Coercing to float both
        # validates them and stops arbitrary text being interpolated into the URL.
        try:
            lat = float(lat)
            lng = float(lng)
        except (TypeError, ValueError):
            logger.warning("GPS coordinates ignored: lat/lng are not numbers")
            return None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            logger.warning("GPS coordinates ignored: lat/lng out of range")
            return None
        started = time.monotonic()
        try:
            query = urllib.parse.urlencode({"format": "json", "lat": lat, "lon": lng})
            req = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/reverse?{query}",
                headers={"User-Agent": "saayam-emergency-api"},
            )
            with urllib.request.urlopen(req, timeout=4) as r:
                data = json.load(r)
                addr = data.get("address", {})
                location = {
                    "zip": addr.get("postcode"),
                    "city": (
                        addr.get("city")
                        or addr.get("town")
                        or addr.get("village")
                    ),
                    "state": addr.get("state"),
                    "country": addr.get("country_code", "").upper()
                }
        except Exception as e:
            logger.warning(
                "Nominatim reverse lookup failed for lat~%s lng~%s: %s (%d ms)",
                _coarse(lat), _coarse(lng), _lookup_failure_reason(e), _elapsed_ms(started),
            )
            return None
        if location["country"]:
            logger.info(
                "Nominatim reverse lookup: lat~%s lng~%s -> %s (%d ms)",
                _coarse(lat), _coarse(lng), _describe(location), _elapsed_ms(started),
            )
        else:
            logger.warning(
                "Nominatim reverse lookup for lat~%s lng~%s returned no country (%d ms)",
                _coarse(lat), _coarse(lng), _elapsed_ms(started),
            )
        return location

    def _geocode_place(self, zip_code=None, city=None, state=None, country=None):
        # Place names are user text, so they are percent-encoded rather than
        # pasted into the URL: a name containing & or # would otherwise
        # silently change the request.
        parts = [str(p).strip() for p in (zip_code, city, state, country) if p]
        if not parts:
            return None
        text = ", ".join(parts)
        started = time.monotonic()
        try:
            query = urllib.parse.urlencode({"format": "json", "limit": 1, "q": text})
            req = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/search?{query}",
                headers={"User-Agent": "saayam-emergency-api"},
            )
            with urllib.request.urlopen(req, timeout=4) as r:
                results = json.load(r)
            if not results:
                logger.warning(
                    "Nominatim place search found no match for %r (%d ms)",
                    text, _elapsed_ms(started),
                )
                return None
            place = results[0]
            lat, lon = place["lat"], place["lon"]
        except Exception as e:
            logger.warning(
                "Nominatim place search failed for %r: %s (%d ms)",
                text, _lookup_failure_reason(e), _elapsed_ms(started),
            )
            return None
        return self._reverse_geocode(lat, lon)

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
            if matches:
                logger.info(
                    "city %r is in the directory for %d countries (%s); not guessing which",
                    city_norm, len(matches), ", ".join(sorted(m["country"] for m in matches)),
                )
            return None
        return matches[0]

    def resolve(self, params, data):
        location = {}
        source = "none"
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
                source = "gps"
        elif zip_code or city or state:
            geo = self._geocode_place(
                zip_code=zip_code, city=city,
                state=state, country=params.get("country")
            )
            if geo:
                location.update(geo)
                source = "place"

        if city and not location.get("country"):
            inferred = self._infer_state_country_from_city(city, data)
            if inferred:
                location.update(inferred)
                source = "city_directory"

        if country_override:
            # An explicit country wins. The finer-grained fields resolved from
            # somewhere else are then discarded: a state or city belonging to a
            # different country would otherwise be looked up inside this one and
            # match by coincidence.
            if location.get("country") and location["country"] != country_override:
                location = {}
            location["country"] = country_override
            source = "country_param"

        if not location.get("country") and self.client_ip:
            if lat and lng:
                # The case behind the Prague report: the browser sent a
                # position, but it did not resolve to a country, so the answer
                # now depends on where the caller's network appears to be.
                logger.warning(
                    "GPS coordinates did not resolve to a country; using the caller's IP (%s) instead",
                    _mask_ip(self.client_ip),
                )
            ip_loc = self._get_location_from_ip(self.client_ip)
            for k, v in ip_loc.items():
                if v:
                    location.setdefault(k, v)
            if location.get("country"):
                source = "ip"

        self.source = source if location.get("country") else "none"
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


def _log_request(params, client_ip):
    """One line describing what the caller sent, before anything is resolved.

    Coordinates are rounded and the IP is masked; the login token and other
    headers never reach this function.
    """
    lat, lng = params.get("lat"), params.get("lng")
    logger.info(
        "emergency request: gps=%s lat~%s lng~%s zip=%s city=%s state=%s country=%s "
        "service=%s language=%s ip=%s params=%s",
        bool(lat and lng), _coarse(lat), _coarse(lng),
        params.get("zip"), params.get("city"), params.get("state"), params.get("country"),
        params.get("service"), params.get("language"), _mask_ip(client_ip),
        # Names only, never values: a client that sends "latitude" instead of
        # "lat" shows up here as the reason a position was ignored.
        sorted(str(k) for k in params),
    )


def get_emergency_services(params, client_ip):
    started = time.monotonic()
    _log_request(params, client_ip)
    try:
        service_resolver = EmergencyServiceResolver()
        data = service_resolver.load_data()

        location_resolver = LocationResolver(client_ip)
        location = location_resolver.resolve(params, data)

        services, level = service_resolver.find_services(
            location, params.get("service")
        )

        if not services:
            country = _normalize_country(location.get("country"))
            if not country:
                reason = "no country could be resolved"
            elif params.get("service"):
                reason = f"no {params.get('service')} number for {country}"
            else:
                reason = f"no numbers for {country}"
            logger.warning(
                "emergency response: status=404 reason=%s source=%s area=%s (%d ms)",
                reason, location_resolver.source, _describe(location), _elapsed_ms(started),
            )
            return {"status": 404, "body": {"error": "Emergency services not found"}}

        language = params.get("language") or "en"
        localization = LocalizationService()
        localized = localization.localize_services(services, language)

        logger.info(
            "emergency response: status=200 country=%s match_level=%s source=%s area=%s "
            "numbers=%s general_fallback=%s for %s (%d ms)",
            _normalize_country(location.get("country")), level, location_resolver.source,
            _describe(location),
            {k: v["dial_number"] for k, v in localized.items() if not v["is_fallback"]},
            next((v["dial_number"] for v in localized.values() if v["is_fallback"]), None),
            sorted(k for k, v in localized.items() if v["is_fallback"]),
            _elapsed_ms(started),
        )

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
        logger.exception(
            "emergency response: status=500 (%s) after %d ms", type(e).__name__, _elapsed_ms(started)
        )
        return {"status": 500, "body": {"error": str(e)}}
