
"""
app/routes/search.py
"""

from flask import Blueprint, request, jsonify
from app.auth.current_user import AuthenticationRequired, get_current_user
from app.repositories.db_search import SearchBackendUnavailable
from app.services.universal_search_service import UniversalSearchService

# The API prefix is configured at app startup so the route can be mounted
# to different gateway stages or deployment paths without changing code.
search_bp = Blueprint("search", __name__)


def _parse_integer(value, default):
    """Return an integer value, falling back for invalid JSON numbers."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _invalid_query_response():
    return jsonify({
        "success": False,
        "message": "Search query must be a string",
        "query": "",
        "page": 1,
        "limit": 10,
        "total": 0,
        "auto_navigate": False,
        "target": None,
        "results": [],
    }), 400


def _error_response(message, status_code, error_code):
    return jsonify({
        "success": False,
        "message": message,
        "error_code": error_code,
        "query": "",
        "page": 1,
        "limit": 10,
        "total": 0,
        "auto_navigate": False,
        "target": None,
        "results": [],
    }), status_code


@search_bp.route("/search", methods=["GET", "POST"])
def universal_search():
    """
    GET /<api-prefix>/search?q=<query>&page=<int>&limit=<int>
    POST /<api-prefix>/search

    JSON payload:
    {
        "q": "<query>",
        "page": <int>,
        "limit": <int>
    }

    Returns JSON:
    {
        "success": bool,
        "message": str,
        "query": str,
        "page": int,
        "limit": int,
        "total": int,
        "auto_navigate": bool,   # true = UI should redirect to target directly
        "target": dict | null,   # the single destination when auto_navigate=true
        "results": [...]
    }
    """
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({
                "success": False,
                "message": "Invalid or missing JSON body",
                "query": "",
                "page": 1,
                "limit": 10,
                "total": 0,
                "auto_navigate": False,
                "target": None,
                "results": [],
            }), 400

        query = data.get("q", "")
        if not isinstance(query, str):
            return _invalid_query_response()

        query = query.strip()
        page = data.get("page", 1)
        limit = data.get("limit", 10)
    else:
        query = request.args.get("q", "").strip()
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 10, type=int)

    page = _parse_integer(page, 1)
    limit = _parse_integer(limit, 10)

    try:
        current_user = get_current_user()
    except AuthenticationRequired:
        return _error_response(
            "Authentication is required",
            401,
            "authentication_required",
        )

    service = UniversalSearchService()
    try:
        response = service.search(
            query=query,
            page=page,
            limit=limit,
            current_user=current_user,
        )
    except SearchBackendUnavailable:
        return _error_response(
            "Search is temporarily unavailable",
            503,
            "search_backend_unavailable",
        )

    status_code = 200 if response["success"] else 400
    return jsonify(response), status_code
