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
from app.repositories.category_search_repo import search_categories
from app.repositories.company_search_repo import search_companies
from app.utils.search_utils import should_auto_navigate

# Input validation constants (per MOM: 2–200 characters)
_MIN_QUERY_LENGTH = 2
_MAX_QUERY_LENGTH = 200
_MAX_LIMIT = 20


class UniversalSearchService:

    def search(self, query: str, page: int, limit: int, current_user) -> dict:
        # --- Sanitize & validate ---
        query = (query or "").strip()
        page  = max(1, page)
        limit = max(1, min(limit or 10, _MAX_LIMIT))

        if not query:
            return self._error("Search query is required", query, page, limit)

        if len(query) < _MIN_QUERY_LENGTH:
            return self._error(
                f"Search query must be at least {_MIN_QUERY_LENGTH} characters",
                query, page, limit,
            )

        if len(query) > _MAX_QUERY_LENGTH:
            return self._error(
                f"Search query must be at most {_MAX_QUERY_LENGTH} characters",
                query, page, limit,
            )

        # -----------------------------------------------------------------------
        # PHASE 1 — Confident Search (GenAI team)
        # If the query looks like a known ID format and a record exists,
        # short-circuit immediately. No fuzzy search needed.
        # -----------------------------------------------------------------------
        confident_result = confident_search(query, current_user)

        if confident_result is not None:
            return {
                "success": True,
                "message": "Exact match found",
                "query": query,
                "page": 1,
                "limit": limit,
                "total": 1,
                "auto_navigate": True,       # UI should redirect directly
                "target": confident_result,
                "results": [confident_result],
            }

        # -----------------------------------------------------------------------
        # PHASE 2 — Fuzzy / Universal Search (DB team handles pg_trgm layer)
        # Each repo applies role-based authorization before filtering.
        # -----------------------------------------------------------------------
        results = []
        results.extend(search_help_requests(query, current_user))
        results.extend(search_users(query, current_user))
        results.extend(search_organizations(query, current_user))
        results.extend(search_categories(query, current_user))
        results.extend(search_companies(query, current_user))

        # Sort: score descending, then entity_type for stable ordering
        results.sort(key=lambda item: (-item.get("score", 0), item.get("entity_type", "")))

        total = len(results)
        start = (page - 1) * limit
        paginated = results[start : start + limit]

        # should_auto_navigate: True only when exactly 1 result with score >= 95
        auto_navigate = should_auto_navigate(paginated)
        target = paginated[0] if auto_navigate else None

        return {
            "success": True,
            "message": "Search completed",
            "query": query,
            "page": page,
            "limit": limit,
            "total": total,
            "auto_navigate": auto_navigate,
            "target": target,
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