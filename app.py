
from flask import Flask, jsonify, request, make_response, send_from_directory
from routes.generate_answers import generate_answer_bp
from routes.predict_categories import predict_categories_bp
import os


app = Flask(__name__)

app.register_blueprint(generate_answer_bp)
app.register_blueprint(predict_categories_bp)

# CORS support - handle preflight OPTIONS requests
@app.after_request
def after_request(response):
    """Add CORS headers to all responses."""
    # Use direct assignment to avoid duplicate headers
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

@app.before_request
def handle_preflight():
    """Handle CORS preflight requests."""
    if request.method == "OPTIONS":
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
        return response

@app.route('/')
def home():
    return jsonify({"message": "API is running"})

@app.route('/chatbot')
def chatbot():
    """Serve the chatbot HTML interface."""
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'chatbot.html')



print(app.url_map)


if __name__ == "__main__":
    app.run(debug=True, port=3001)
    
    
    


    