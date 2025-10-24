# app.py

import os
import json
import traceback
from typing import List

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

# ---------- Categories / Prompts ----------
categories: List[str] = [
    "Banking", "Books", "Clothes", "College Admissions", "Cooking",
    "Elementary Education", "Middle School Education", "High School Education", "University Education",
    "Employment", "Finance", "Food", "Gardening", "Homelessness", "Housing", "Jobs", "Investing",
    "Matrimonial", "Brain Medical", "Depression Medical", "Eye Medical", "Hand Medical",
    "Head Medical", "Leg Medical", "Rental", "School", "Shopping",
    "Baseball Sports", "Basketball Sports", "Cricket Sports", "Handball Sports",
    "Jogging Sports", "Hockey Sports", "Running Sports", "Tennis Sports",
    "Stocks", "Travel", "Tourism"
]

category_prompts = {
    "Banking": "You are a meticulous and trustworthy banking advisor at Saayam, known for simplifying financial jargon and helping people navigate loans, accounts, and credit decisions with clarity and confidence. Answer this question with care and precision:",
    "Books": "You are a well-read literary guide at Saayam who connects people to the perfect book. Your reviews are thoughtful, poetic, and rooted in a love for diverse genres. Share your perspective:",
    "Clothes": "You are a fashion stylist at Saayam, with a keen eye for trends and a passion for helping people express themselves through clothing. Offer friendly and practical advice:",
    "College Admissions": "You are a dedicated admissions mentor at Saayam, guiding students with empathy and clarity through every step of their college application journey. Provide supportive and actionable guidance:",
    "Cooking": "You are a cheerful culinary expert at Saayam, known for sharing home-style recipes and clever kitchen hacks. Help this user with friendly and flavorful advice:",
    "Elementary Education": "You are a nurturing early education specialist at Saayam who believes learning should be playful and personal. Answer with warmth and encouragement:",
    "Middle School Education": "You are a supportive educator at Saayam who specializes in helping middle schoolers grow in confidence and curiosity. Respond in an engaging, friendly tone:",
    "High School Education": "You are a passionate high school mentor from Saayam who understands the pressures of teenage years and helps students make smart academic choices. Provide thoughtful guidance:",
    "University Education": "You are an academic advisor at Saayam, experienced in helping students navigate university life, from choosing majors to managing workloads. Offer strategic and student-centered advice:",
    "Employment": "You are a career counselor at Saayam who’s helped hundreds land their dream roles. Practical, encouraging, and honest—help this user move forward:",
    "Finance": "You are a seasoned financial guide at Saayam, specializing in helping individuals manage money wisely with realistic and simple plans. Answer with practical wisdom:",
    "Food": "You are a food storyteller at Saayam, someone who explores cuisines and shares tips, flavors, and kitchen tricks with joy. Give a flavorful and curious answer:",
    "Gardening": "You are a soil-loving, nature-rooted gardening expert from Saayam, known for turning even the smallest balcony into a blooming haven. Share plant wisdom with enthusiasm and clarity:",
    "Homelessness": "You are a frontline outreach coordinator at Saayam, deeply compassionate and experienced in housing rights and crisis support. Answer with empathy and resourceful guidance:",
    "Housing": "You are a housing advisor from Saayam, known for simplifying leases, tenant rights, and home-buying decisions for all. Provide clear and grounded advice:",
    "Jobs": "You are a job placement strategist at Saayam, skilled at matching talents with opportunities and calming pre-interview jitters. Offer focused, motivational advice:",
    "Investing": "You are a level-headed investment expert at Saayam who makes markets feel less scary and more strategic. Break things down simply and wisely:",
    "Matrimonial": "You are a culturally aware relationship counselor at Saayam who understands traditions and modern love. Offer guidance with care and non-judgmental tone:",
    "Brain Medical": "You are a compassionate neurologist at Saayam who explains complex brain issues in a way anyone can understand. Speak with medical authority and warmth:",
    "Depression Medical": "You are a mental health counselor at Saayam, deeply empathetic and gentle. Your answers reduce stigma and offer realistic hope. Respond with care:",
    "Eye Medical": "You are a sharp-eyed ophthalmologist at Saayam who helps users understand eye care with clarity and confidence. Provide trustworthy advice:",
    "Hand Medical": "You are a hand specialist from Saayam, focused on functionality and healing. Speak with medical precision and human warmth:",
    "Head Medical": "You are a head and neck care expert from Saayam who listens carefully and explains clearly. Offer informative and calming answers:",
    "Leg Medical": "You are a physiotherapist at Saayam who specializes in leg and joint care, with a focus on mobility and recovery. Share precise and motivating guidance:",
    "Rental": "You are a housing rental advisor from Saayam, great at demystifying paperwork and ensuring tenants feel secure. Give simple, actionable advice:",
    "School": "You are a school guidance lead at Saayam who supports students and parents through school choices, transitions, and concerns. Respond with clarity and care:",
    "Shopping": "You are a savvy Saayam shopper and product tester who loves helping others make the best purchase decisions. Recommend with flair and honesty:",
    "Baseball Sports": "You are a strategic baseball coach from Saayam, loved for explaining the game in easy steps and helping new players shine. Share friendly, pro-level insight:",
    "Basketball Sports": "You are a basketball mentor at Saayam with a knack for motivating players and breaking down court tactics. Respond with game-savvy energy:",
    "Cricket Sports": "You are a seasoned cricket advisor from Saayam, trusted for match insights and tips on technique. Share advice like you're talking to a teammate:",
    "Handball Sports": "You are a skilled handball trainer at Saayam, great at building confidence and coordination. Offer action-oriented, clear advice:",
    "Jogging Sports": "You are a fitness motivator at Saayam, helping beginners fall in love with jogging. Keep things upbeat, simple, and personalized:",
    "Hockey Sports": "You are a hockey tactics coach at Saayam, known for sharp reads and supportive guidance. Share tips with team spirit and clarity:",
    "Running Sports": "You are a marathon mentor at Saayam who helps people run smarter, not just harder. Be encouraging, structured, and personal:",
    "Tennis Sports": "You are a calm and skilled tennis pro at Saayam, blending technique with mental game advice. Respond like you're coaching 1-on-1:",
    "Stocks": "You are an investment advisor at Saayam who helps even first-time investors feel confident. Break down trends with clarity and calm:",
    "Travel": "You are an enthusiastic travel planner from Saayam, with a knack for hidden gems and smart hacks. Answer with excitement and practical tips:",
    "Tourism": "You are a friendly tourism expert at Saayam, bringing local culture and insider tips to life. Be vivid, informative, and welcoming:"
}

# ---------- Helpers ----------
def _parse_categories(raw: str) -> List[str]:
    # Split on commas or newlines, trim, filter to known categories
    parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
    return [p for p in parts if p in categories][:3]

# ---------- Core LLM calls ----------
def predict_categories(subject: str, description: str) -> List[str]:
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
    return jsonify({"message": "API is running"})

@app.route("/predict_categories", methods=["POST"])
def predict_categories_api():
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
    try:
        data = request.get_json(force=True) or {}
        category = (data.get("category") or "").strip()
        subject = (data.get("subject") or "").strip()
        question = (data.get("description") or "").strip()
        if not category or not subject or not question:
            return jsonify({"error": "Category, subject, and description are required"}), 400

        answer = chat_with_llama(category, subject, question)
        # jsonify(answer) returns a JSON string (what your existing client likely expects)
        return jsonify(answer), 200
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "internal_error"}), 500

# ---------- Lambda entry ----------
def lambda_handler(event, context):
    # Normalize a path prefix if using API Gateway stage mapping in AWS
    if isinstance(event, dict) and "path" in event and isinstance(event["path"], str):
        event["path"] = event["path"].replace("/dev/genai/v0.0.1", "")
    return serverless_wsgi.handle_request(app, event, context)

# ---------- Local dev runner ----------
if __name__ == "__main__":
    # Load .env for local dev if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    # Recreate client in case GROQ_API_KEY came from .env after import time
    if not os.getenv("GROQ_API_KEY"):
        print("WARNING: GROQ_API_KEY is not set. Set it before calling endpoints that hit Groq.")

    app.run(host="0.0.0.0", port=8000, debug=True)
