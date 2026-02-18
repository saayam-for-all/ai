import os

# Base directory of the project (root level)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Path to emergency numbers JSON — can be overridden via environment variable
DATA_FILE = os.getenv(
    "EMERGENCY_DATA_FILE",
    os.path.join(BASE_DIR, "data", "emergency_numbers.json")
)

# Geocoding config
NOMINATIM_USER_AGENT = os.getenv("NOMINATIM_USER_AGENT", "ngo-emergency-api")
GEOCODE_TIMEOUT = int(os.getenv("GEOCODE_TIMEOUT", "4"))

# IP geolocation config
IPINFO_TIMEOUT = int(os.getenv("IPINFO_TIMEOUT", "3"))
IPINFO_URL = os.getenv("IPINFO_URL", "https://ipinfo.io")

# Fallback country if nothing else resolves
DEFAULT_COUNTRY = os.getenv("DEFAULT_COUNTRY", "US")