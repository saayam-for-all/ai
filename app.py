
from flask import Flask, jsonify, request, make_response
from routes.generate_answers import generate_answer_bp
from routes.predict_categories import predict_categories_bp


app = Flask(__name__)

app.register_blueprint(generate_answer_bp)
app.register_blueprint(predict_categories_bp)

@app.route('/')
def home():
    return jsonify({"message": "API is running"})



print(app.url_map)


if __name__ == "__main__":
    app.run(debug=True)
    
    
    


    