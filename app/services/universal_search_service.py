from app.repositories.help_request_search_repo import search_help_requests
from app.repositories.user_search_repo import search_users
from app.repositories.organization_search_repo import search_organizations
from app.repositories.category_search_repo import search_categories
from app.repositories.company_search_repo import search_companies
from app.utils.search_utils import should_auto_navigate


class UniversalSearchService:
    MAX_LIMIT = 20
    MIN_QUERY_LENGTH = 2

    def search(self, query: str, page: int, limit: int, current_user) -> dict:
        query = (query or "").strip()

        # Validate pagination
        if page < 1:
            page = 1

        if limit < 1:
            limit = 10
        if limit > self.MAX_LIMIT:
            limit = self.MAX_LIMIT

        # Validate query
        if not query:
            return {
                "success": False,
                "message": "Search query is required",
                "query": query,
                "page": page,
                "limit": limit,
                "total": 0,
                "results": [],
            }

        # Allow short numeric IDs if needed.
        # For now, keep it simple and require 2 chars minimum.
        if len(query) < self.MIN_QUERY_LENGTH:
            return {
                "success": False,
                "message": "Search query must be at least 2 characters",
                "query": query,
                "page": page,
                "limit": limit,
                "total": 0,
                "results": [],
            }

        # Search each entity independently with authorization-aware queries.
        results = []
        results.extend(search_help_requests(query, current_user))
        results.extend(search_users(query, current_user))
        results.extend(search_organizations(query, current_user))
        results.extend(search_categories(query, current_user))
        results.extend(search_companies(query, current_user))

        # Sort by score descending, then entity type for stable ordering
        results.sort(
            key=lambda item: (-item.get("score", 0), item.get("entity_type", ""))
        )

        total = len(results)
        start = (page - 1) * limit
        end = start + limit
        paginated_results = results[start:end]

        auto_navigate = should_auto_navigate(paginated_results)
        target = paginated_results[0] if auto_navigate else None

        return {
            "success": True,
            "message": "Search completed",
            "query": query,
            "page": page,
            "limit": limit,
            "total": total,
            "auto_navigate": auto_navigate,
            "target": target,
            "results": paginated_results,
        }