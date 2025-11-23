from flask import request, jsonify, Blueprint
from services import get_service_wrapper
from utils.subject_generator import generate_subject_from_description

predict_categories_bp = Blueprint('predict_categories', __name__)


class SaayamPredictCategoriesAPI:
    """Class-based API for category prediction."""
    
    @staticmethod
    def predict_categories_api():
        """
        Predict categories based on subject and description.
        
        Returns:
            JSON response with predicted categories or error message
        """
        data = request.get_json()
        subject = data.get("subject")
        description = data.get("description")

        # Description is required
        if not description:
            return jsonify({"error": "Description is required"}), 400
        
        # Generate subject from description if not provided
        if not subject or not subject.strip():
            print("Subject not provided, generating from description...")
            subject = generate_subject_from_description(description, max_length=70)
            print(f"Generated subject: {subject}")

        try:
            service_wrapper = get_service_wrapper()
            predicted_categories = service_wrapper.predict_categories(subject, description)
            response = jsonify(predicted_categories)
            # CORS headers are handled globally in app.py
            
            return response
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# Predict categories based on subject and description
@predict_categories_bp.route('/predict_categories', methods=['POST'])
def predict_categories_api():
    return SaayamPredictCategoriesAPI.predict_categories_api()
