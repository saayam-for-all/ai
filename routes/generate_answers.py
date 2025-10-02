from utils.categories import help_categories
from services.generate_answer_service import chat_with_llama
from flask import jsonify, request, make_response, Blueprint
# from app import app

generate_answer_bp = Blueprint('generate_answer', __name__)

#Generate an answer based on category constant, subject, description, location and gender
@generate_answer_bp.route('/generate_answer', methods=['POST'])
def generate_answer_api():
    data = request.get_json()
    category = data.get("category")
    subject = data.get("subject")
    question = data.get("description")
    location = data.get("location")
    gender = data.get("gender")
    print(gender)

    if not category or not subject or not question or not location:
        return jsonify({"error": "Category, subject, description and location are required"}), 400

    try:
        category = help_categories[category]
        answer = chat_with_llama(category, subject, question, location, gender)
        response = jsonify(answer)
        #print("Respose body:", response)            
        # Adding headers. Pl modify * to our release website address in production
        response.headers['Access-Control-Allow-Origin'] = '*'
        
        return response
        #return jsonify(answer)  
    except Exception as e:
        return jsonify({"error": str(e)}), 500