from flask import Flask, render_template, request, jsonify
from transformers import pipeline
from groq import Groq
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()
groq_api_key = os.getenv("GROQ_API_KEY")
os.environ["GROQ_API_KEY"] = groq_api_key

# Initialize GROQ client
client = Groq()

# Category list for classification
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

# Zero-shot classification pipeline
classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

# Flask app setup
app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html', categories=categories)

@app.route('/predict_categories', methods=['POST'])
def predict_categories():
    data = request.get_json()
    subject = data.get("subject")
    description = data.get("description")

    if not subject or not description:
        return jsonify({"error": "Subject and description required"}), 400

    prompt = f"{subject}. {description}"
    try:
        result = classifier(prompt, categories)
        return jsonify({"predicted_categories": result['labels'][:3]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generate_answer', methods=['POST'])
def generate_answer():
    data = request.get_json()
    category = data.get("category")
    question = data.get("question")

    if not category or not question:
        return jsonify({"error": "Category and question are required"}), 400

    prompt = f"Category: {category}\nQuestion: {question}"

    try:
        response = client.chat.completions.create(
            model="llama-3.2-1b-preview",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        return jsonify({"answer": response.choices[0].message.content.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
