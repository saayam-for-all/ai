from flask import request, jsonify, Blueprint
from services import get_service_wrapper
from utils.categories import help_categories
from utils.subject_generator import generate_subject_from_description

generate_answer_bp = Blueprint('generate_answer', __name__)


class SaayamGenerateAnswerAPI:
    """Class-based API for answer generation."""
    
    @staticmethod
    def generate_answer_api():
        """
        Generate a conversational answer with context maintenance.
        Accepts conversation history to maintain context across multiple turns.
        
        Expected JSON format:
        {
            "category": "string",
            "subject": "string (optional - will be auto-generated from description if not provided)",
            "description": "string (current user message)",
            "location": "string (optional)",
            "gender": "string (optional)",
            "age": "string (optional)",
            "conversation_history": [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."},
                ...
            ] (optional)
        }
        
        Returns:
            JSON response with generated answer or error message
        """
        data = request.get_json()
        category = data.get("category")
        subject = data.get("subject")
        question = data.get("description")
        location = data.get("location")  # Optional - can be None
        gender = data.get("gender")  # Optional - can be None
        age = data.get("age")  # Optional - can be None
        conversation_history = data.get("conversation_history", [])  # Optional - list of previous messages
        
        print(f"Gender: {gender}, Location: {location}, Age: {age}")
        print(f"Conversation history length: {len(conversation_history)}")

        # Category and description are required
        if not category or not question:
            return jsonify({"error": "Category and description are required"}), 400
        
        # Track if subject was auto-generated
        subject_was_generated = False
        
        # Generate subject from description if not provided
        if not subject or not subject.strip():
            print("Subject not provided, generating from description...")
            subject = generate_subject_from_description(question, max_length=70)
            subject_was_generated = True
            print(f"Generated subject: {subject}")

        # Validate conversation history format if provided
        if conversation_history:
            if not isinstance(conversation_history, list):
                return jsonify({"error": "conversation_history must be a list"}), 400
            for msg in conversation_history:
                if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                    return jsonify({"error": "Each message in conversation_history must have 'role' and 'content' fields"}), 400
                if msg["role"] not in ["user", "assistant"]:
                    return jsonify({"error": "Message role must be 'user' or 'assistant'"}), 400

        try:
            # Handle both numeric keys (e.g., "1.1") and category constants (e.g., "FOOD_ASSISTANCE")
            if category in help_categories:
                # Category is a numeric key, get the category constant
                category = help_categories[category]
            elif category in help_categories.values():
                # Category is already a category constant, use it directly
                pass
            else:
                # Try "General" as fallback, or raise error
                if category == "General" or category == "0.0.0.0.0":
                    category = "General"
                else:
                    raise KeyError(f"Invalid category: {category}. Must be a key from help_categories or a valid category constant.")
            
            service_wrapper = get_service_wrapper()
            answer = service_wrapper.generate_answer(
                category, subject, question, location, gender, age, conversation_history
            )
            
            # Return answer with generated subject if it was auto-generated
            # Maintain backward compatibility: if subject wasn't generated, return just the answer string
            if subject_was_generated:
                response_data = {
                    "answer": answer,
                    "subject": subject,
                    "subject_generated": True
                }
                return jsonify(response_data)
            else:
                # Backward compatibility: return just the answer string if subject was provided
                return jsonify(answer)
        except KeyError as e:
            print(f"KeyError: {str(e)}")
            return jsonify({"error": f"Invalid category: {str(e)}"}), 400
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Error in generate_answer_api: {str(e)}")
            print(f"Traceback: {error_trace}")
            return jsonify({"error": str(e), "traceback": error_trace}), 500


# Generate a conversational answer with context maintenance
@generate_answer_bp.route('/generate_answer', methods=['POST'])
def generate_answer_api():
    return SaayamGenerateAnswerAPI.generate_answer_api()
