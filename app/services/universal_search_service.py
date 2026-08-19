"""
app/services/universal_search_service.py

Search flow (GenAI team owns Phase 1, DB team owns Phase 2):

  Phase 1 — Confident Search (this file + confident_search_repo.py)
    ↓  If exact ID match found → return immediately, auto_navigate=True
    ↓  No match → fall through

  Phase 2 — Fuzzy Search (DB team: pg_trgm / GIN indexes)
    ↓  Fan-out across all entity repos
    ↓  Score, sort, paginate
"""

from app.repositories.confident_search_repo import confident_search
from app.repositories.help_request_search_repo import search_help_requests
from app.repositories.user_search_repo import search_users
from app.repositories.organization_search_repo import search_organizations
from app.repositories.db_search import SearchBackendUnavailable
from app.extensions import db
from sqlalchemy.exc import SQLAlchemyError

# Input validation constants (per MOM: 2–200 characters)
_MIN_QUERY_LENGTH = 2
_MAX_QUERY_LENGTH = 200
_MAX_LIMIT = 20
_MAX_PER_ENTITY_CANDIDATES = 100


class UniversalSearchService:
    def search(self, query: str, page: int, limit: int, current_user) -> dict:
        # --- Sanitize & validate ---
        query = (query or "").strip()
        page = max(1, page)
        limit = max(1, min(limit or 10, _MAX_LIMIT))

        if not query:
            return self._error("Search query is required", query, page, limit)

        if len(query) < _MIN_QUERY_LENGTH:
            return self._error(
                f"Search query must be at least {_MIN_QUERY_LENGTH} characters",
                query,
                page,
                limit,
            )

        if len(query) > _MAX_QUERY_LENGTH:
            return self._error(
                f"Search query must be at most {_MAX_QUERY_LENGTH} characters",
                query,
                page,
                limit,
            )

        # -----------------------------------------------------------------------
        # PHASE 1 — Confident Search (GenAI team)
        # If the query looks like a known ID format and a record exists,
        # short-circuit immediately. No fuzzy search needed.
        # -----------------------------------------------------------------------
        try:
            confident_result = confident_search(query, current_user)
        except SQLAlchemyError as exc:
            db.session.rollback()
            raise SearchBackendUnavailable(
                "Database search is unavailable"
            ) from exc

        if confident_result is not None:
            return {
                "success": True,
                "message": "Exact match found",
                "query": query,
                "page": 1,
                "limit": limit,
                "total": 1,
                "auto_navigate": True,  # UI should redirect directly
                "target": confident_result,
                "results": [confident_result],
            }

        # -----------------------------------------------------------------------
        # PHASE 2 — Fuzzy / Universal Search (DB team handles pg_trgm layer)
        # Each repo applies role-based authorization before filtering.
        # -----------------------------------------------------------------------
        per_entity_limit = min(page * limit, _MAX_PER_ENTITY_CANDIDATES)
        results = []
        results.extend(search_help_requests(query, current_user, per_entity_limit))
        results.extend(search_users(query, current_user, per_entity_limit))
        results.extend(search_organizations(query, current_user, per_entity_limit))

        # A result can appear through multiple aliases. Keep the highest-scored
        # occurrence while preserving cross-entity results.
        deduplicated = {}
        for item in results:
            key = (item.get("entity_type"), item.get("entity_id"))
            current = deduplicated.get(key)
            if current is None or item.get("score", 0) > current.get("score", 0):
                deduplicated[key] = item
        results = list(deduplicated.values())

        # Sort: score descending, then entity_type for stable ordering
        results.sort(
            key=lambda item: (
                -item.get("score", 0),
                item.get("entity_type", ""),
            )
        )

        total = len(results)
        start = (page - 1) * limit
        paginated = results[start : start + limit]

        return {
            "success": True,
            "message": "Search completed",
            "query": query,
            "page": page,
            "limit": limit,
            "total": total,
            # Navigation is reserved for Phase 1 exact matches. A fuzzy score,
            # even a strong one, must still be confirmed by the user.
            "auto_navigate": False,
            "target": None,
            "results": paginated,
        }

    # ---------------------------------------------------------------------------
    @staticmethod
    def _error(message: str, query: str, page: int, limit: int) -> dict:
        return {
            "success": False,
            "message": message,
            "query": query,
            "page": page,
            "limit": limit,
            "total": 0,
            "auto_navigate": False,
            "target": None,
            "results": [],
        }
