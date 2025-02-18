import os
from flask import Flask, render_template_string, jsonify, request
from groq import Groq
from transformers import pipeline
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Securely fetch the API key
API_KEY = os.getenv("GROQ_API_KEY")
if not API_KEY:
    raise ValueError("GROQ_API_KEY is missing. Please set it in the .env file.")

# Initialize Groq client
client = Groq(api_key=API_KEY)

# Define categories for zero-shot classification
categories = [
    "Banking", "Books", "Clothes", "College Admissions", "Cooking",
    "Elementary Education", "Middle School Education", "High School Education", "University Education",
    "Employment", "Finance", "Food", "Gardening", "Homelessness", "Housing", "Jobs", "Investing",
    "Matrimonial", "Brain Medical", "Depression Medical", "Eye Medical", "Hand Medical",
    "Head Medical", "Leg Medical", "Rental", "School", "Shopping",
    "Baseball Sports", "Basketball Sports", "Cricket Sports", "Handball Sports",
    "Jogging Sports", "Hockey Sports", "Running Sports", "Tennis Sports",
    "Stocks", "Travel", "Tourism"
]

# Load the zero-shot classification model
classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

def predict_categories(subject, description):
    """
    Predicts top 3 relevant categories based on the subject and description.
    """
    try:
        prompt = f"{subject}. {description}"
        result = classifier(prompt, categories)
        return result['labels'][:3]  # Return top 3 predicted categories
    except Exception as e:
        print(f"Error in category prediction: {e}")
        return []

def chat_with_llama(category, description):
    """
    Generates AI-based responses using LLaMA 3.2 model.
    """
    try:
        full_prompt = f"Category: {category}\nQuestion: {description}"
        response = client.chat.completions.create(
            model="llama-3.2-1b-preview",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": full_prompt}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error in AI response generation: {e}")
        return "Sorry, an error occurred while generating the response."

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return jsonify({"message": "Saayam AI Assistant is running"}), 200

@app.route('/predict_categories', methods=['POST'])
def predict_categories_api():
    """
    API endpoint to predict categories based on user input.
    """
    data = request.get_json()
    subject = data.get("subject")
    description = data.get("description")

    if not subject or not description:
        return jsonify({"error": "Subject and description are required"}), 400

    try:
        predicted_categories = predict_categories(subject, description)
        return jsonify({"predicted_categories": predicted_categories}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generate_answer', methods=['POST'])
def generate_answer_api():
    """
    API endpoint to generate answers based on user input.
    """
    data = request.get_json()
    category = data.get("category")
    question = data.get("question")

    if not question or not category:
        return jsonify({"error": "Question and category are required"}), 400

    try:
        answer = chat_with_llama(category, question)
        return jsonify({"answer": answer}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
