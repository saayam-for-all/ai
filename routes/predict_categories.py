from flask import request, jsonify, Blueprint
from services.classification_service import predict_categories
# from app import app

predict_categories_bp = Blueprint('predict_categories', __name__)

#Predict categories based on subject and description
@predict_categories_bp.route('/predict_categories', methods=['POST'])
def predict_categories_api():
    data = request.get_json()
    subject = data.get("subject")
    description = data.get("description")

    if not subject or not description:
        return jsonify({"error": "Subject and description are required"}), 400
    
    # if description is 'geneal'.lower():
    #     predict_categories(subject=subject, description= description)

    try:
        predicted_categories = predict_categories(subject, description)
        response = jsonify(predicted_categories)
        #print("Respose body:", response)            
        # Adding headers. Pl modify * to our release website address in production
        response.headers['Access-Control-Allow-Origin'] = '*'
        
        #return jsonify(predicted_categories)  # Return only categories
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500