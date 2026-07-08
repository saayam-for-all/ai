# app.py

import os
import json
import traceback
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, jsonify, request
from groq import Groq
import serverless_wsgi

# ---------- App setup ----------
app = Flask(__name__)
app.config["PROPAGATE_EXCEPTIONS"] = True

# Simple CORS for dev; tighten for prod
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

# ---------- Groq client ----------
# Read key from environment (set GROQ_API_KEY in shell or .env)
print("GROQ key present at startup:", bool(os.getenv("GROQ_API_KEY")))
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MODEL_NAME = "llama-3.1-8b-instant"

# ---------- Categories / Prompts Loader ----------
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "configs", "categories.json")

categories: List[str] = []
category_prompts = {}

def load_config():
    """
    Loads categories and persona prompts from configs/categories.json.
    Falls back to a default set of categories and prompts if the file
    is missing, malformed, or empty.
    """
    global categories, category_prompts
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config_data = json.load(f)
                categories = config_data.get("categories", [])
                category_prompts = config_data.get("category_prompts", {})
                print(f"Successfully loaded {len(categories)} categories from config.")
        else:
            print(f"WARNING: Config file not found at {CONFIG_PATH}. Using fallbacks.")
    except Exception as e:
        print(f"ERROR: Failed to load config from {CONFIG_PATH}: {e}")

    # Fallbacks in case config is empty or invalid
    if not categories:
        categories = ["Finance", "Housing", "Jobs", "Banking", "Health", "Education"]
    if not category_prompts:
        category_prompts = {
            "Finance": "You are a seasoned financial guide at Saayam, specializing in helping individuals manage money wisely with realistic and simple plans. Answer with practical wisdom:",
            "Housing": "You are a housing advisor from Saayam, known for simplifying leases, tenant rights, and home-buying decisions for all. Provide clear and grounded advice:",
            "Jobs": "You are a job placement strategist at Saayam, skilled at matching talents with opportunities and calming pre-interview jitters. Offer focused, motivational advice:"
        }

# Initial configuration load
load_config()

# ---------- Helpers ----------
def _parse_categories(raw: str) -> List[str]:
    """
    Splits the LLM output raw string on commas or newlines, trims whitespace,
    filters the result against the list of known valid categories,
    and returns up to three matched categories.
    """
    parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
    return [p for p in parts if p in categories][:3]

# ---------- Core LLM calls ----------
def predict_categories(subject: str, description: str) -> List[str]:
    """
    Uses the Groq LLM to predict up to 3 relevant categories for a given
    subject and description. Falls back to a default list if the model
    response does not match any valid predefined categories.
    """
    prompt = f"""
You are a zero-shot text classifier that classifies user input into exactly three categories from the predefined list below.
Respond ONLY with a comma-separated list of categories. Do not include any additional text or explanations.

Categories: {", ".join(categories)}

User Input:
Subject: {subject}
Description: {description}

Output (comma-separated categories):
""".strip()

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        top_p=0.3,
    )
    raw_output = resp.choices[0].message.content.strip()
    result = _parse_categories(raw_output)

    # Fallback: if model returns nothing valid, return first three general categories
    if not result:
        result = ["Finance", "Housing", "Jobs"][:3]
    return result


def chat_with_llama(category: str, subject: str, description: str) -> str:
    """
    Generates a helpful, persona-driven expert response using the Groq LLM
    based on the specified category, subject, and description.
    """
    role_prompt = category_prompts.get(
        category,
        "You are a helpful expert from Saayam. Answer the question clearly and kindly:",
    )
    full_prompt = f"{role_prompt}\n\nSubject: {subject}\nQuestion: {description}"

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": full_prompt}],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()

# ---------- Routes ----------
@app.route("/", methods=["GET"])
def home():
    """
    Simple health check route to verify that the API is running.
    """
    return jsonify({"message": "API is running"})

@app.route("/predict_categories", methods=["POST"])
def predict_categories_api():
    """
    REST API endpoint to predict categories for a query.
    Expects a POST request with 'subject' and 'description' in the JSON body.
    """
    try:
        data = request.get_json(force=True) or {}
        subject = (data.get("subject") or "").strip()
        description = (data.get("description") or "").strip()
        if not subject or not description:
            return jsonify({"error": "Subject and description are required"}), 400

        cats = predict_categories(subject, description)
        return jsonify(cats), 200
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "internal_error"}), 500

@app.route("/generate_answer", methods=["POST"])
def generate_answer_api():
    """
    REST API endpoint to generate a persona-driven answer.
    Expects a POST request with 'category', 'subject', and 'description' (question).
    """
    try:
        data = request.get_json(force=True) or {}
        category = (data.get("category") or "").strip()
        subject = (data.get("subject") or "").strip()
        question = (data.get("description") or "").strip()
        if not category or not subject or not question:
            return jsonify({"error": "Category, subject, and description are required"}), 400

        answer = chat_with_llama(category, subject, question)
        return jsonify(answer), 200
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "internal_error"}), 500

# ---------- Lambda entry ----------
def lambda_handler(event, context):
    """
    AWS Lambda entry point. Standard Serverless WSGI handler
    that strips API stage prefixes if present.
    """
    # Normalize a path prefix if using API Gateway stage mapping in AWS
    if isinstance(event, dict) and "path" in event and isinstance(event["path"], str):
        event["path"] = event["path"].replace("/dev/genai/v0.0.1", "")
    return serverless_wsgi.handle_request(app, event, context)

# ---------- Local dev runner ----------
if __name__ == "__main__":
    # Check if GROQ_API_KEY is set
    if not os.getenv("GROQ_API_KEY"):
        print("WARNING: GROQ_API_KEY is not set. Set it before calling endpoints that hit Groq.")

    app.run(host="0.0.0.0", port=8000, debug=True)
