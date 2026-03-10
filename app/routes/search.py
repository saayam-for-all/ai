from flask import Blueprint, request, jsonify
from app.auth.current_user import get_current_user
from app.services.universal_search_service import UniversalSearchService

search_bp = Blueprint("search", __name__, url_prefix="/api")


@search_bp.route("/api/search", methods=["GET"])
def universal_search():
    query = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 10, type=int)

    current_user = get_current_user()

    service = UniversalSearchService()
    response = service.search(
        query=query,
        page=page,
        limit=limit,
        current_user=current_user,
    )

    status_code = 200 if response["success"] else 400
    return jsonify(response), status_code