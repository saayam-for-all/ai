
from flask import Flask, jsonify, request, make_response
from routes.generate_answers import generate_answer_bp
from routes.predict_categories import predict_categories_bp

# from utils.prompts import category_prompts
# from utils.categories import help_categories
# from utils.categories_with_description import TAXONOMY


#Set up temporary local databse of categories and categories constant


# Set up categories 
# categories = [
#     "Food & Essentials", "Clothing Support", "Housing Assistance", "Education & Career Support", "Healthcare & Wellness", "Elderly & Community Support"

# ]

app = Flask(__name__)

app.register_blueprint(generate_answer_bp)
app.register_blueprint(predict_categories_bp)

@app.route('/')
def home():
    return jsonify({"message": "API is running"})






if __name__ == "__main__":
    app.run(debug=True)
    
    
    


    