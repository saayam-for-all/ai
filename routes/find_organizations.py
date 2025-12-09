from flask import request, jsonify, Blueprint
from services.organization_search_service import GeminiOrganizationSearchService

find_organizations_bp = Blueprint('find_organizations', __name__)


class SaayamFindOrganizationsAPI:
    """Class-based API for finding organizations."""
    
    @staticmethod
    def find_organizations_api():
        """
        Find organizations based user help request and context.

        Expected JSON format:
        {
            "category": "string",
            "subject": "string",
            "description": "string",
            "location": "string (optional)",
        }
        Returns:
            Data about relevant organizations
        """
        data = request.get_json()
        subject = data.get("subject") or "General support"
        description = data.get("description")
        location = data.get("location")

        if not description:
            return jsonify({"error": "description is required"}), 400

        try:
            service = GeminiOrganizationSearchService()
            organizations = service.find_organizations(subject=subject, description=description, location=location)
            return jsonify({"organizations": organizations})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500


@find_organizations_bp.route('/find_organizations', methods=['POST'])
def find_organizations_api():
    return SaayamFindOrganizationsAPI.find_organizations_api()