from flask import request, jsonify, Blueprint
from utils.subject_generator import generate_subject_from_description

generate_subject_bp = Blueprint('generate_subject', __name__)


class SaayamGenerateSubjectAPI:
    """Class-based API for subject generation."""
    
    @staticmethod
    def generate_subject_api():
        """
        Generate a concise subject from a description.
        
        Expected JSON format:
        {
            "description": "string (required)",
            "max_length": "integer (optional, default: 70)"
        }
        
        Returns:
            JSON response with generated subject or error message
        """
        data = request.get_json()
        description = data.get("description") if data else None
        max_length = data.get("max_length", 70) if data else 70

        # Description is required
        if not description:
            return jsonify({"error": "Description is required"}), 400

        # Validate max_length
        try:
            max_length = int(max_length)
            if max_length < 1 or max_length > 200:
                return jsonify({"error": "max_length must be between 1 and 200"}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "max_length must be a valid integer"}), 400

        try:
            generated_subject = generate_subject_from_description(description, max_length=max_length)
            
            return jsonify({
                "subject": generated_subject,
                "max_length": max_length,
                "description_length": len(description)
            })
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Error in generate_subject_api: {str(e)}")
            print(f"Traceback: {error_trace}")
            return jsonify({"error": str(e), "traceback": error_trace}), 500


# Generate subject from description
@generate_subject_bp.route('/generate_subject', methods=['POST'])
def generate_subject_api():
    return SaayamGenerateSubjectAPI.generate_subject_api()

