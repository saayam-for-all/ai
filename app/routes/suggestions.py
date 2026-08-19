"""
app/routes/suggestions.py
"""

from flask import Blueprint, request, jsonify
from app.auth.current_user import AuthenticationRequired, get_current_user
from app.repositories.db_search import SearchBackendUnavailable
from app.services.suggestion_service import SuggestionService

# The API prefix is configured at app startup so this route can be mounted
# under whatever gateway stage path is required.
suggestions_bp = Blueprint("suggestions", __name__)


def _parse_integer(value, default):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _error_response(message, status_code, error_code):
    return jsonify({
        "success": False,
        "message": message,
        "error_code": error_code,
        "query": "",
        "limit": 10,
        "total": 0,
        "results": [],
    }), status_code


@suggestions_bp.route("/suggestions", methods=["GET", "POST"])
def suggestions():
    """
    GET /<api-prefix>/suggestions?q=<query>&limit=<int>
    POST /<api-prefix>/suggestions

    JSON payload:
    {
        "q": "<query>",
        "limit": <int>
    }

    Returns JSON:
    {
        "success": bool,
        "message": str,
        "query": str,
        "limit": int,
        "total": int,
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
                "limit": 10,
                "total": 0,
                "results": [],
            }), 400

        query = data.get("q", "")
        if not isinstance(query, str):
            return _error_response(
                "Search query must be a string",
                400,
                "invalid_query_type",
            )
        query = query.strip()
        limit = data.get("limit", 10)
    else:
        query = request.args.get("q", "").strip()
        limit = request.args.get("limit", 10, type=int)

    limit = _parse_integer(limit, 10)

    try:
        current_user = get_current_user()
    except AuthenticationRequired:
        return _error_response(
            "Authentication is required",
            401,
            "authentication_required",
        )
    service = SuggestionService()
    try:
        response = service.suggest(
            query=query,
            limit=limit,
            current_user=current_user,
        )
    except SearchBackendUnavailable:
        return _error_response(
            "Suggestions are temporarily unavailable",
            503,
            "search_backend_unavailable",
        )

    status_code = 200 if response["success"] else 400
    return jsonify(response), status_code
