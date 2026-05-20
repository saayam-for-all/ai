"""
app/services/suggestion_service.py
"""

from app.repositories.suggestion_search_repo import search_suggestions
from app.utils.search_utils import normalize_query

_MIN_QUERY_LENGTH = 1
_MAX_QUERY_LENGTH = 100
_MAX_LIMIT = 20


class SuggestionService:

    def suggest(self, query: str, limit: int, current_user) -> dict:
        query = normalize_query(query)
        limit = max(1, min(limit or 10, _MAX_LIMIT))

        if len(query) > _MAX_QUERY_LENGTH:
            return {
                "success": False,
                "message": f"Search query must be at most {_MAX_QUERY_LENGTH} characters",
                "query": query,
                "limit": limit,
                "total": 0,
                "results": [],
            }

        if not query:
            return {
                "success": True,
                "message": "No query provided",
                "query": query,
                "limit": limit,
                "total": 0,
                "results": [],
            }

        results = search_suggestions(query, current_user, limit)
        return {
            "success": True,
            "message": "Suggestions fetched",
            "query": query,
            "limit": limit,
            "total": len(results),
            "results": results,
        }
