import json
from config import DATA_FILE, DEFAULT_COUNTRY


class EmergencyService:
    """Handles loading emergency data and resolving the correct emergency services for a location."""

    def __init__(self):
        self._cache = None

    # ------------------ Data Loading ------------------

    def load_emergency_numbers(self):
        """Loads emergency numbers from JSON file. Caches after first load."""
        if self._cache is None:
            with open(DATA_FILE, "r") as f:
                self._cache = json.load(f)
        return self._cache

    # ------------------ Resolver ------------------

    def find_emergency_services(self, location, requested_service=None):
        """
        Resolves the best matching emergency services for a given location.
        Resolution priority: ZIP → City → State → Country → US fallback
        """
        data = self.load_emergency_numbers()

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

        # ZIP (most specific)
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

        # US fallback (last resort)
        us_default = data.get(DEFAULT_COUNTRY, {}).get("default")
        return filter_service(us_default), "country"