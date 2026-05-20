"""
app/routes/suggestions.py
"""

from flask import Blueprint, request, jsonify
from app.auth.current_user import get_current_user
from app.services.suggestion_service import SuggestionService

# The API prefix is configured at app startup so this route can be mounted
# under whatever gateway stage path is required.
suggestions_bp = Blueprint("suggestions", __name__)


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

        query = str(data.get("q", "")).strip()
        limit = data.get("limit", 10)
    else:
        query = request.args.get("q", "").strip()
        limit = request.args.get("limit", 10, type=int)

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10

    current_user = get_current_user()
    service = SuggestionService()
    response = service.suggest(
        query=query,
        limit=limit,
        current_user=current_user,
    )

    status_code = 200 if response["success"] else 400
    return jsonify(response), status_code
